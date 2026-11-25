# Phase 2 runbook: background jobs on AWS Lambda

Implements Phase 2 of [ADR 0001](adr/0001-serverless-background-jobs.md). The Heroku web API
stays as it is; all background work (routine clock, routine runs, push delivery, mediation AI,
image processing) moves to one Lambda function. **Every step that provisions infrastructure or
changes production needs explicit approval.**

## Architecture

```text
Heroku web API ──(async invoke, queue names only)──▶ bibi-jobs:live ◀── EventBridge Scheduler (every minute)
                                                         │
                         SSM /bibi/prod/jobs (secrets) ──┤──▶ MongoDB Atlas (TLS, dedicated user)
                                                         ├──▶ S3 (read images/, thumbnails/; write thumbnails/)
                                                         ├──▶ OpenAI, Web Push services
                                                         └──▶ CloudWatch Logs (JSON, 14 days)
AWS Budget (account-wide) ──▶ email at $2 forecast / $5 actual
```

| Component | Setting |
|---|---|
| Jobs function `bibi-jobs` | Container image (arm64), 512 MB, 900 s timeout, reserved concurrency 1, no VPC |
| Alias `live` | The only invocation target. CI publishes versions and moves it. |
| Async invoke config (on `live`) | 0 retries, 300 s maximum event age |
| Schedule | `rate(1 minute)` → `live`, 0 retries, 60 s event age. **Disabled until cutover.** |
| ECR `bibi-jobs` | Immutable `sha-<commit>` tags, scan on push; keeps the newest 10 deployed images; untagged images expire after 1 day |
| SSM `/bibi/prod/jobs/*` | SecureString, AWS-managed key; values set out of band, never in OpenTofu state |
| Logs | `/aws/lambda/bibi-jobs`, 14-day retention |
| Budget | Account-wide; emails at $2 forecast and $5 actual per month. The only alerting by design: there are no CloudWatch alarms. |
| Observability | Every run logs a `job_run_summary` with `failed_total`, `timed_out_total`, `oldest_overdue_routine_seconds` and `oldest_pending_push_seconds`; inspect these in CloudWatch Logs when something looks wrong |
| GitHub deploy | OIDC role, only for the `jobs-production` environment; can push images, update code, publish versions, smoke-test and move `live` |
| Heroku identity | IAM user allowed only `lambda:InvokeFunction` on `bibi-jobs:live` |

**Ownership split.**
- **OpenTofu** (`infra/jobs`) owns configuration: memory, environment, roles, schedule, budget.
- **CI** (`.github/workflows/deploy-jobs.yml`) owns code: images, versions and the alias.
- OpenTofu ignores `image_uri` and the alias version.
- OpenTofu configuration changes reach `$LATEST`. They take effect with the next CI deployment; run the workflow manually to publish them immediately.

### Security trade-off: public MongoDB endpoint

The Atlas access list already contains `0.0.0.0/0`, because Heroku has no fixed egress IPs. Lambda
connects over the public internet in the same way, so Phase 2 doesn't change the exposure. A NAT
gateway with a static IP (around $35/month) or private endpoints would contradict the cost target
and are out of scope.

The mitigations:
- **Dedicated credentials:** a database user used only by Lambda, limited to `readWrite` on the
  production database.
- **TLS:** `mongodb+srv` URLs with certificate verification. The application refuses insecure
  TLS options when `APP_ENV=prod`.
- **Secret storage:** the URL lives only in SSM Parameter Store.
- **Rotation:** credentials can be rotated without a deploy (update SSM, then publish a new
  version).

## Required configuration values

**OpenTofu** (`infra/jobs/terraform.tfvars`, no secrets):

| Variable | Value |
|---|---|
| `aws_region` | `eu-west-1` (same region as the bucket) |
| `initial_image_tag` | `sha-<commit>` of the first image pushed in step 3 |
| `s3_bucket_name` | Heroku `AWS_S3_BUCKET` |
| `s3_bucket_region` | Heroku `AWS_REGION` (`eu-west-1`) |
| `s3_image_prefix`, `s3_thumbnail_prefix` | Heroku `AWS_S3_IMAGE_FOLDER` / `AWS_S3_THUMBNAIL_FOLDER` (default `images/`, `thumbnails/`) |
| `mongo_app_name` | `production` |
| `web_push_vapid_public_key`, `web_push_vapid_subject` | Same as Heroku |
| `extra_environment` | `OPENAI_MODEL_XIAOBAO`, `OPENAI_MODEL_MEDIATION`, `OPENAI_MODEL_MODERATION`, `THUMBNAIL_SIZE` (copied from Heroku) |
| `budget_email` | Address for the budget alerts |
| `create_github_oidc_provider` | `false` if the account already has one |

**SSM SecureString** under `/bibi/prod/jobs/`:

| Parameter | Value |
|---|---|
| `MONGO_URL` | `mongodb+srv://` URL for a **new dedicated Atlas user** (`readWrite@production` only) |
| `OPENAI_API_KEY` | A dedicated OpenAI project key with a spend limit (recommended), or the current key |
| `XIAOBAO_WEB_PUSH_VAPID_PRIVATE_KEY` | Same as Heroku |
| `XIAOBAO_WEB_PUSH_SUBSCRIPTION_ENCRYPTION_KEY` | Same as Heroku (subscriptions are encrypted with it) |

Set each value without leaving it in shell history:

```bash
read -rs VALUE && aws ssm put-parameter --overwrite --type SecureString \
  --name /bibi/prod/jobs/MONGO_URL --value "$VALUE" && unset VALUE
```

**GitHub:**
- **Environment `jobs-production`:** restricted to the `master` branch.
- **Environment variables:** `AWS_JOBS_DEPLOY_ROLE_ARN` (output `github_deploy_role_arn`), `AWS_REGION`, `JOBS_FUNCTION_NAME=bibi-jobs`, `JOBS_ECR_REPOSITORY=bibi-jobs`.
- **Repository variable:** `JOBS_DEPLOY_ENABLED=true`, once provisioning is done.

**Heroku**, at cutover:

| Variable | Value |
|---|---|
| `JOB_WAKEUP_MODE` | `lambda` |
| `JOB_WAKEUP_LAMBDA_FUNCTION_NAME` | `bibi-jobs:live` (output `heroku_wakeup_function_name`) |
| `JOB_WAKEUP_LAMBDA_REGION` | `eu-west-1` |
| `JOB_WAKEUP_AWS_ACCESS_KEY`, `JOB_WAKEUP_AWS_SECRET_KEY` | Access key of IAM user `bibi-jobs-heroku-wakeup` |
| `MEDIATION_WORKER_ENABLED`, `IMAGE_WORKER_ENABLED` | `false` (after the Lambda has been verified) |

## Provisioning (approval required)

1. **State bucket:** in `infra/bootstrap`, run `tofu init && tofu apply -var state_bucket_name=<unique-name>`. Local state; it holds no secrets.
2. **Repository first:** in `infra/jobs`, run `tofu init -backend-config=backend.hcl`, then
   `tofu apply -target=aws_ecr_repository.jobs -target=aws_ecr_lifecycle_policy.jobs`.
3. **First image:** log in to ECR, then
   `docker buildx build --platform linux/arm64 --target jobs --provenance=false --sbom=false -t <ecr-url>:sha-<commit> --push .`
4. **Everything else:** set `initial_image_tag`, then run a full `tofu apply` (the schedule stays disabled).
5. **Secrets:**
   - Create the dedicated Atlas user.
   - Set the four SSM values.
6. **Heroku identity:** `aws iam create-access-key --user-name bibi-jobs-heroku-wakeup`. Keep the secret out of files and history; it goes only into Heroku at cutover.
7. **GitHub:** create the environment and variables, then run **Deploy jobs Lambda** manually.
   - The run publishes version 1, runs `ensure_indexes` and `smoke` on it, and only then moves `live`.
   - The smoke result (`"mongo": "ok"`) is the **first verified Lambda-to-Atlas connection**, over TLS with the dedicated user.
8. **Unique-index migration** (production database; approval required):
   - Check only, read-only: `heroku run -a counting-down-fastapi python scripts/migrate_mediation_output_unique_index.py`
   - If it reports no duplicates, apply: `... --apply --confirm-database production`
   - If duplicates are found, nothing changes; resolve them deliberately first (ADR 0001).

## Cutover (approval required)

The Lambda and the Heroku in-process workers can run side by side safely: every queue claims
work with leases, so each step is reversible.

1. Set `schedule_enabled = true` and run `tofu apply`. The Lambda now serves every queue,
   including routines and push for the first time. Watch two runs of `job_run_summary` in the
   logs.
2. Set the Heroku wake-up variables. Uploads, mediation requests and push tests now wake the
   Lambda immediately.
3. After the validation below passes, set `MEDIATION_WORKER_ENABLED=false` and
   `IMAGE_WORKER_ENABLED=false` on Heroku. The web dyno no longer polls the database.

## Validation procedure

Use synthetic content and your own accounts. Each check names its pass signal.

| # | Check | How | Pass signal |
|---|---|---|---|
| 1 | Connectivity | `aws lambda invoke --function-name bibi-jobs --qualifier live --cli-binary-format raw-in-base64-out --payload '{"task":"smoke"}' out.json` | `"mongo": "ok"`, `"push_configured": true`, `"openai_configured": true` |
| 2 | Scheduled routine | Ask Xiao Bao for a daily suggestion due 3 minutes from now and accept the proposal | Inbox message within about 2 minutes of the due time; `job_run_summary` shows `processed.routine` |
| 3 | One-time reminder | Ask for a reminder 2 minutes from now and accept | Delivered once; the routine shows as completed |
| 4 | Push on a physical device | Install the PWA, enable notifications, send a test push; then wait for check 2 | Test push arrives within seconds (wake-up), routine push after its message; one notification each |
| 5 | Mediation | Synthetic session with both perspectives | Reflections, then advice; one output per job (`ai_job_id`); no `failed` in summaries |
| 6 | Image processing | Upload a test photo | Thumbnails appear; `processed.image` |
| 7 | Retry and lease recovery | Drill: `aws lambda put-function-concurrency --function-name bibi-jobs --reserved-concurrent-executions 0` for 12 minutes during check 2, then restore to 1 (or `tofu apply`) | Summaries resume after restore with `oldest_overdue_routine_seconds` back at 0; the backlog is processed exactly once |
| 8 | Concurrent wake-ups | Send 5 push tests in quick succession | Each delivered once; at most expected throttles, no `failed` |
| 9 | Duplicate prevention | Repeat a push test with the same request (double tap); after the migration, check outputs per `ai_job_id` | One delivery per request; migration check reports 0 duplicates |
| 10 | Observability | During drill 7, run a CloudWatch Logs Insights query on `event = "job_run_summary"` | Summaries show `failed_total`, `timed_out_total` and the overdue ages; the budget email address is confirmed in AWS Budgets |
| 11 | Rollback | Rehearse the rollback below for 10 minutes, then go forward again | Heroku processes mediation and images; the Lambda shows no invocations |

## Rollback

Each step is independent and takes effect in seconds:

- **Bad code:** move the alias back. Every deploy's job summary prints the exact command:
  `aws lambda update-alias --function-name bibi-jobs --name live --function-version <previous>`.
- **Back to Heroku execution:**
  1. On Heroku, set `MEDIATION_WORKER_ENABLED=true` and `IMAGE_WORKER_ENABLED=true`, and
     `JOB_WAKEUP_MODE=none`.
  2. Set `schedule_enabled = false` and run `tofu apply`. In an emergency, use
     `aws scheduler update-schedule` to disable it, then reconcile OpenTofu.
  3. Routines and push then return to their pre-Phase-2 state (inactive). Optionally set
     `XIAOBAO_IN_PROCESS_JOBS_ENABLED=true` on Heroku; on Eco that only runs while the dyno is
     awake.
- **No data rollback is needed:** queues keep their state, and in-flight items are recovered
  through their leases.

## Costs (current usage: 2 users)

| Item | Monthly usage | Within free allowance | Without free allowance |
|---|---|---|---|
| Lambda requests | ~45k (43.8k schedule ticks + wake-ups) | $0 | ~$0.01 |
| Lambda compute | ~2–5k GB-s (idle ticks 5–30 ms; routine and mediation AI time) | $0 | ~$0.03–0.07 |
| EventBridge Scheduler | 43.8k invocations | $0 (14M free) | ~$0.04 |
| CloudWatch Logs | ~50–80 MB ingested, 14-day retention | $0 (5 GB) | ~$0.05 |
| ECR | ≤10 images; shared layers, roughly 0.3–0.5 GB | — | ~$0.03–0.05 |
| SSM Standard parameters, AWS-managed KMS key | 4 | $0 | $0 |
| S3 state bucket | a few KB | — | <$0.01 |
| AWS Budget | 1 budget without actions | $0 | $0 |
| **Total** | | **≈ $0.05–0.10** | **≈ $0.20 worst case** |

Without CloudWatch alarms or custom metrics, the cost stays well under $1/month even if other
projects in the account already use the free allowances.
