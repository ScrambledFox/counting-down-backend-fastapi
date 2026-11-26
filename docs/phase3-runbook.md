# Phase 3 runbook: the API on AWS Lambda

ADR 0001, Phase 3. Moves the HTTP API from the Heroku Eco dyno to a Lambda function with a public,
response-streaming Function URL. The background jobs already run on Lambda (Phase 2). Every step
marked **approval** changes production and needs the owner's explicit go-ahead.

## What changes

| | Before | After |
|---|---|---|
| API | Heroku Eco dyno; sleeps after 30 min, about 13–14 s to wake | Lambda `bibi-api`, 1024 MB, arm64, reserved concurrency 5; cold start of a few seconds |
| Address | `counting-down-fastapi-….herokuapp.com/api/v1` | `https://<id>.lambda-url.eu-west-1.on.aws/api/v1` (Vercel `VITE_API_BASE_URL`) |
| Photo uploads | Multipart through the API | Browser → S3 with a presigned POST; the API records the upload |
| AWS access | Static S3 and wake-up keys on Heroku | The function's IAM role; no static keys |
| Abuse and cost guards | Xiao Bao chat limit only | Plus failed-login limits, a daily AI budget and a mediation allowance |
| Cost | $5/month (Eco) | About $0–1/month within the free allowances |

The API and jobs functions share the OpenTofu root `infra/jobs` (state, budget, GitHub role).
The new resources are in `api.tf` and `api_iam.tf`.

## Safeguards (application-level; no API Gateway)

| Guard | Default | Setting |
|---|---|---|
| Failed logins per client address | 10 per 15 min, then HTTP 429 | `LOGIN_MAX_FAILURES_PER_CLIENT`, `LOGIN_FAILURE_WINDOW_SECONDS` |
| Failed logins overall | 100 per hour, then login pauses | `LOGIN_MAX_FAILURES_GLOBAL`, `LOGIN_GLOBAL_FAILURE_WINDOW_SECONDS` |
| AI requests (chat, mediation, routines) | 500 per UTC day | `AI_DAILY_REQUEST_LIMIT` |
| Mediation AI runs per person | 30 per UTC day | `MEDIATION_AI_DAILY_RUNS_PER_USER` |
| Concurrent API instances | 5 | `api_reserved_concurrency` (tfvars) |

Counters live in the `usage_counters` collection (TTL-expired); client addresses are stored only
as a short hash. Set a limit to `0` to disable it. Change limits with `extra_environment` in
tfvars (API and jobs both read it) and `tofu apply`; no code change is needed.

## Configuration values

- **tfvars** (local, git-ignored): `api_initial_image_tag`, and `frontend_origins` copied from
  Heroku's `FRONTEND_URLS` (`https://www.bibi-zhuzhu.nl`, `https://counting-down-self.vercel.app`,
  `https://counting-down.lovable.app`; add `https://bibi-zhuzhu.nl` if the apex domain serves the
  site).
- **SSM `/bibi/prod/api/*`** (SecureString, set out of band, never printed):
  - `MONGO_URL`, `OPENAI_API_KEY`, `XIAOBAO_WEB_PUSH_VAPID_PRIVATE_KEY`,
    `XIAOBAO_WEB_PUSH_SUBSCRIPTION_ENCRYPTION_KEY`: copied from `/bibi/prod/jobs/*` (the
    dedicated Atlas user has `readWrite` on `production` only, which is what the API needs).
  - `ACCESS_KEY_DANFENG`, `ACCESS_KEY_JORIS`, `AERODATABOX_API_KEY`: copied from Heroku.
- **GitHub** environment `jobs-production`: variables `API_FUNCTION_NAME=bibi-api` and
  `API_ECR_REPOSITORY=bibi-api`; repository variable `API_DEPLOY_ENABLED=true`.
- **Vercel** at cutover: `VITE_API_BASE_URL=<api_url output>api/v1` (Production), then rebuild.

## Provisioning (approval)

```bash
cd infra/jobs
export AWS_PROFILE=mototrack-dev AWS_REGION=eu-west-1
tofu init -backend-config=backend.hcl
tofu apply -target=aws_ecr_repository.api          # 1. the repository
# 2. Build and push the first image (from the repository root):
docker buildx build --platform linux/arm64 --target api --provenance=false --sbom=false \
  -t <api_ecr_repository_url>:sha-<commit> --push .
# 3. Set api_initial_image_tag = "sha-<commit>" in terraform.tfvars, review, apply:
tofu plan    # expect only additions plus the GitHub deploy policy update
tofu apply
```

The apply creates the function, its `live` alias and Function URL, IAM, log group, SSM
placeholders, the ECR lifecycle policy, and the image bucket's CORS rule (the bucket had none;
only its CORS configuration is managed). The function fails closed until the secrets are set.

## Cutover (approval at each step)

1. **Secrets:** copy the SSM values listed above with a script that never prints them.
2. **GitHub:** set the two variables and `API_DEPLOY_ENABLED=true`.
3. **Merge the backend PR.** Three deploys follow automatically:
   - Heroku gets the new endpoints (the old multipart ones stay).
   - The jobs deploy runs `ensure_indexes` (TTL indexes for `usage_counters` and `image_uploads`).
   - The API deploy publishes a version, checks `/health/ready` on it and moves `live`.
4. **Check the Lambda API directly:** `/health`, `/health/ready`, a CORS preflight from
   `https://www.bibi-zhuzhu.nl`, a wrong login (403) and an `X-Forwarded-For` check in the logs.
5. **Merge the frontend PR** (direct uploads). It still talks to Heroku; upload a photo and an
   advent picture to prove the S3 form and bucket CORS work.
6. **Switch:** set `VITE_API_BASE_URL` in Vercel and rebuild production. Sessions live in
   MongoDB, so nobody is logged out.
7. **Validate** (below). Then scale the Heroku dyno to 0 (`heroku ps:scale web=0`) for a soak
   period of about two weeks.
8. **Decommission (separate approval):** delete the Heroku app, delete the invoke-only IAM user
   `bibi-jobs-heroku-wakeup` and its key, and rotate or remove the static S3 key Heroku used.

## Validation

| # | Check | Pass condition |
|---|---|---|
| 1 | Cold start | First request after 15+ min idle answers within about 5 s; `Init Duration` in `/aws/lambda/bibi-api` REPORT lines |
| 2 | Login | Correct key logs in; 10 wrong keys from one device give 429 for 15 min, the other device still logs in |
| 3 | Xiao Bao chat | Tokens stream in gradually (not all at once); the reply is stored |
| 4 | Disconnect | Closing the drawer mid-reply leaves the message `CANCELLED` or `COMPLETE`, never stuck `GENERATING` |
| 5 | Photo upload | A photo over 5 MB uploads; thumbnail appears within about a minute (jobs) |
| 6 | Advent upload | Item and its thumbnail appear |
| 7 | Gallery | Images and thumbnails load, including after an hour (presigned GETs signed with role credentials) |
| 8 | Mediation | Submitting a perspective queues AI work; the jobs function processes it |
| 9 | Push | Subscribing on a phone works; a reminder delivers |
| 10 | Logs | No session IDs, access keys or presigned URLs in `/aws/lambda/bibi-api` |
| 11 | Rollback rehearsal | Moving `live` to the previous version works |

## Rollback

- **Bad API code:** `aws lambda update-alias --function-name bibi-api --name live --function-version <previous>` (the deploy summary prints it).
- **Back to Heroku:** `heroku ps:scale web=1`, remove `VITE_API_BASE_URL` in Vercel and rebuild
  (production builds fall back to the Heroku URL). Direct uploads keep working there: Heroku
  signs the S3 forms with its existing key.
- **Disable the public URL in an emergency:** set the API's reserved concurrency to 0
  (`aws lambda put-function-concurrency --function-name bibi-api --reserved-concurrent-executions 0`).

## Costs (2 users)

| | Monthly |
|---|---|
| Lambda API (a few thousand requests, 1 GB) | $0 within the free allowance |
| ECR (second repository, about 0.25 GB per image, 10 kept) | about $0.10–0.25 |
| CloudWatch Logs | $0 at this volume |
| Heroku Eco, after decommissioning | −$5 |

The account-wide budget (`bibi-monthly`: $2 forecast, $5 actual) covers both functions.
