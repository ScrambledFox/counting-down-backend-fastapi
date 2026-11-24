# ADR 0001: Serverless hosting with finite, event-driven background jobs

- **Status:** Accepted (direction). Phase 1 implemented; Phases 2 and 3 pending review.
- **Date:** 2026-11-24
- **Deciders:** Joris (owner), with Claude Code as implementer
- **Scope:** `counting-down-fastapi` hosting and background execution; `counting-down` API URL
  configuration.

## Context

BIBI Dairy is used by two people. The backend runs on one Heroku Eco web dyno. The Procfile
declared three more always-on processes (`clock`, `worker`, `push-worker`). They are scaled to 0,
so Xiao Bao routines and push notifications were deployed but not executing. The web process also
ran two in-process polling loops (mediation AI every 2 s, image jobs every 30 s), which stop
whenever the Eco dyno sleeps.

Running every process on Heroku Basic would cost about $28/month, or $14/month consolidated.
The target is $0–5/month without reducing functionality, reliability or privacy.

Investigation showed that every background queue already lives in MongoDB with leases, attempt
limits, back-off and duplicate guards, and each worker already exposes a "process one item"
function. Continuous execution was an implementation choice; only time-based wake-ups (routines
falling due, retry back-off, expired leases, the inactivity auto-pause) are inherent.

## Decision

Adopt a lean serverless architecture on AWS (option A), reached incrementally through a hybrid
stage (option B):

- Two Lambda functions built from one source tree and dependency set:
  - **API:** FastAPI behind the Lambda Web Adapter on a response-streaming Function URL.
  - **Jobs:** a handler that processes available work and exits.
- One recurring EventBridge Scheduler schedule (every minute) invokes the jobs function. The API
  asynchronously invokes it after creating work.
- MongoDB collections remain the durable job queues and the single source of truth. No SQS, no
  per-routine AWS schedules.
- Existing MongoDB Atlas, S3 and Vercel stay as they are. OpenTofu provisions AWS resources.
- No API Gateway, SQS, NAT gateway, load balancer or continuously running compute unless a
  demonstrated requirement emerges.
- A scheduling delay of about one minute under normal operation is acceptable.

## Phase 1 implementation (this change)

| Area | Change |
|---|---|
| Job runner | `app/workers/job_runner.py`: two concurrent lanes. **Fast:** routine clock, push. **Slow:** routine runs, mediation, image, round-robin, one item at a time. Finite mode (deadline) and continuous mode (stop event) share all logic. |
| Bounded execution | Each item runs under `asyncio.wait_for` with a timeout inside its lease (`within_lease`: push 45 s of 60 s; routine, mediation and image 240 s of 300 s). No item starts unless its timeout fits before the deadline. Cancellation equals a crash: the lease expires and the item is retried. |
| Single-item functions | Extracted for mediation and image jobs; the Xiao Bao workers already had them. Endless loops removed. |
| Entry points | `python -m app.workers.drain [--loop]` (local, Heroku); `app/lambda_jobs.py` (Lambda, persistent event loop because Motor binds its client to one loop). Every invocation serves every queue. |
| Wake-ups | `app/services/job_wakeup.py`: `none` (default) or `lambda` (asynchronous `Event` invoke). Payload is `{"kinds": [...]}` only. Failures are logged by error type and never fail the request. Wired after mediation job creation, image upload, thumbnail requests and push tests. |
| Configuration | `XIAOBAO_IN_PROCESS_JOBS_ENABLED`, `ENSURE_INDEXES_ON_STARTUP`, `MONGO_MAX_POOL_SIZE`, `JOB_WAKEUP_MODE`, `JOB_WAKEUP_LAMBDA_FUNCTION_NAME`. Existing `IMAGE_WORKER_ENABLED` and `MEDIATION_WORKER_ENABLED` keep their meaning. |
| Indexes | `app/db/indexes.py` and `scripts/ensure_indexes.py` (deploy-time, idempotent). |
| AWS credentials | `app/core/aws.py`: Heroku's `AWS_ACCESS_KEY`/`AWS_SECRET_KEY` when both are set, otherwise the default credential provider chain (IAM role, profile). |
| Dependencies | `fastapi[standard]` replaced by the parts in use (`fastapi`, `uvicorn[standard]`, `python-multipart`, `httpx`). Test and type-stub packages moved to dev. `awslambdaric` sits in an optional `lambda` group. |
| Containers | One `Dockerfile`, two arm64 targets (`api`, `jobs`) sharing all dependency and source layers (see "One image or two" below). |
| Heroku | Procfile: `web` plus one `worker: python -m app.workers.drain --loop`. Production behaviour is unchanged until a worker is scaled. |

## Amendments and how they are addressed

| # | Requirement | Status | How |
|---|---|---|---|
| 1 | Verify MongoDB Atlas network access; do not broaden it without approval | **Open: gate for Phase 2** | Not verifiable from the repository (no Atlas API access). Heroku Eco has no fixed egress IPs, so the access list is presumably already open to all addresses, but this is unconfirmed. Before Phase 2 the owner confirms the current list. If it is restricted, Lambda (no fixed egress without a NAT gateway) needs a separately approved alternative. No Atlas setting is changed by this work. |
| 2 | Application-level rate limiting and AI consumption safeguards before exposing the API through Lambda | **Planned: gate for Phase 3** | Today: Xiao Bao chat has a per-user Mongo-backed limit (`XIAOBAO_RATE_LIMIT_REQUESTS`). Missing: login brute-force protection, a mediation AI cap, and a global AI spend guard. Phase 3 is blocked until all three exist, alongside reserved concurrency and an OpenAI project budget. |
| 3 | Long-running jobs must not indefinitely delay push or scheduled routines | **Done** | Separate fast lane for clock and push. The fast lane keeps polling while slow work runs, and makes a final pass when it finishes. Per-item timeouts. Tested (`test_push_is_not_delayed_by_long_running_slow_job`). |
| 4 | Bounded async invocation retries and event expiry; MongoDB stays the source of truth | **Planned: Phase 2 infrastructure** | `aws_lambda_function_event_invoke_config` on the jobs function: `maximum_retry_attempts = 0`, `maximum_event_age_in_seconds = 300`. Losing a wake-up is harmless because the one-minute schedule recovers the work. The schedule target itself gets `maximum_retry_attempts = 0` and a 120 s event age, since the next tick supersedes it. |
| 5 | Monitor async event age, dropped events and overdue jobs | **Planned: Phase 2** | Alarms on `AsyncEventAge` (p99 > 120 s) and `AsyncEventsDropped`, plus jobs-function `Errors` and `Throttles`. Overdue work: the jobs handler logs, via Embedded Metric Format, the age of the oldest due push delivery and routine run, alarmed at 5 and 10 minutes. This stays within the 10 free custom metrics. |
| 6 | Test crash recovery, expired leases, concurrent wake-ups and duplicate execution | **Done** | New: push lease expiry and fencing, concurrent runners on real Mongo claims, duplicate push-test enqueue, stale mediation recovery and idempotent creation, runner timeout and deadline, Lambda handler loop reuse. Existing: routine duplicate-worker repair, routine lease expiry, image claim races. |
| 7 | No exactly-once push claim; best-effort dedupe | **Done (documented)** | Delivery is at-least-once. Deduplication: one delivery per (message, device) via upsert; lease-token fencing so a superseded runner cannot acknowledge; the service worker uses `tag = message id` with `renotify: false`, so a repeat silently replaces the first notification. A crash between sending and recording can still repeat a push. |
| 8 | Protect ECR images referenced by active and rollback versions | **Planned: Phase 2** | Images are tagged with the commit SHA. CI keeps the last 5 published Lambda versions and deletes older versions before their images. The ECR lifecycle policy expires only untagged images and SHA tags beyond the newest 10, which is more than the retained versions. Rollback targets stay within the retained set. |
| 9 | One shared image vs two build targets | **Resolved** | One Dockerfile, one dependency layer and one source layer, two thin targets. The `api` target adds the Web Adapter extension and the uvicorn command; the `jobs` target sets the runtime-interface-client entry point. A single image would put the Web Adapter extension into the jobs function, where it expects an HTTP server. In ECR the shared layers are stored once, and building `jobs` after `api` reuses every cached layer. |
| 10 | Verify auth, cookies, CORS, SSE, client disconnects and S3 before API migration | **Planned: gate for Phase 3** | Checklist in the Phase 3 plan below, run against a non-production function URL with synthetic data. |
| 11 | Free allowances are shared with other projects | **Accepted, with a recommendation** | Lambda, EventBridge Scheduler and CloudWatch free allowances apply per account (CloudWatch per region). Recommendation: a dedicated AWS account for BIBI in an AWS Organization (no cost), so allowances, budgets and the blast radius are isolated. Budgets alert on forecast and actual spend in any case. |
| 12 | Infrastructure and CI must not compete over Lambda versions and aliases | **Planned: Phase 2** | OpenTofu owns function configuration, roles, the Function URL, concurrency, the schedule and alarms, and ignores `image_uri` and the alias `function_version`. CI owns image builds, `UpdateFunctionCode`, `PublishVersion` and moving the `live` alias. Neither tool touches the other's attributes. |

## Rejected alternatives

- **API Gateway HTTP API:** cannot stream responses, has a ~30 s timeout, and charges per request
  after the first year.
- **SQS between the API and the jobs function:** duplicates the existing MongoDB queues and leases.
- **One EventBridge schedule per routine:** a second source of truth for times that the app
  already computes, including DST handling.
- **A single Heroku Basic dyno:** simplest, but $7/month and keeps static AWS keys.
- **Google Cloud Run:** a second cloud provider and cross-cloud S3 credentials.
- **A VPS:** operating-system and TLS maintenance.

## Consequences

- Routines start within about one minute of their due time (previously ≤15 s with an always-on
  clock).
- Idle cost is near zero. An empty scheduled run takes 20–30 ms in the Lambda emulator.
- Pushes remain at-least-once.
- Mediation completion is not fenced by a lease token, unlike push and routine runs. A duplicate is
  prevented only because the item timeout (240 s) is shorter than the stale threshold (300 s).
  Adding fencing is a recommended follow-up.

## Phase 2 plan: background work on AWS (hybrid)

Preconditions:
- Atlas access list confirmed (amendment 1).
- An AWS account chosen (dedicated account recommended).

Work:
1. **OpenTofu module** (`infra/`), applied by the owner. State in S3 with native lock files.
   - ECR repository and lifecycle policy (amendment 8).
   - Jobs function (arm64, 512 MB, 900 s timeout, reserved concurrency 1), with a `live` alias.
   - Async invoke config (amendment 4).
   - One EventBridge schedule `rate(1 minute)` targeting the alias, plus its role.
   - SSM SecureString parameter names. Values are entered by hand and kept out of state.
   - Log group with 14-day retention.
   - Alarms (amendment 5) and an SNS email topic.
   - AWS Budget alerts at $2 forecast and $5 actual.
   - GitHub OIDC deploy role limited to ECR push, code update, version publish and alias update
     on the jobs function.
   - IAM user for Heroku limited to `lambda:InvokeFunction` on the jobs alias.
2. **CI workflow** on push to `master`, after tests:
   - build `jobs` for arm64 and push it tagged with the SHA;
   - run `scripts/ensure_indexes.py`;
   - update the code, publish a version, run a smoke test on the version, then move the alias;
   - prune versions beyond five.
3. **Jobs handler:** read secrets from SSM at cold start and emit the overdue-work metrics.
4. **Heroku configuration:**
   - `JOB_WAKEUP_MODE=lambda` and the function name;
   - `MEDIATION_WORKER_ENABLED=false`, `IMAGE_WORKER_ENABLED=false`;
   - no `worker` dyno.
5. **Verification in production with synthetic data:**
   - push test from a phone;
   - a one-off reminder two minutes ahead;
   - a daily routine end to end;
   - a mediation request;
   - a photo upload with its thumbnail;
   - forced timeout and redrive checks.
6. **Rollback:** set `JOB_WAKEUP_MODE=none`, re-enable the web flags, and optionally scale the
   Heroku `worker`.

## Phase 3 plan: API on Lambda

Preconditions: amendments 2 and 10 complete.

- **Compatibility checklist:**
  - `X-Session-Id` authentication and frontend cookie storage;
  - CORS for the Vercel origins (application-managed, not Function URL CORS);
  - SSE streaming through the Web Adapter, including time-to-first-token;
  - client disconnects mid-stream (the generation is persisted or cancelled cleanly);
  - multipart image upload size limits;
  - image byte endpoints over 6 MB (prefer presigned URLs);
  - presigned S3 upload and download;
  - push subscription flow;
  - cold-start latency.
- **Cutover:** API function with a streaming Function URL and reserved concurrency; set
  `VITE_API_BASE_URL` in Vercel. Heroku stays at zero dynos for a soak period, then is
  decommissioned only with explicit approval, and its static AWS keys are rotated and removed.
