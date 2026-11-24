# ADR 0001: Serverless hosting with finite, event-driven background jobs

- **Status:** Accepted (direction). Phase 1 implemented and revised after review; Phases 2 and 3
  pending approval.
- **Dates:** 2026-11-24 (decision, Phase 1), 2026-11-25 (review fixes)
- **Deciders:** Joris (owner), with Claude Code as implementer
- **Scope:** `counting-down-fastapi` hosting and background execution; `counting-down` API URL
  configuration.

## Context

BIBI Dairy is used by two people. The backend runs on one Heroku Eco web dyno. The Procfile
declared three more always-on processes (`clock`, `worker`, `push-worker`). They are scaled to 0,
so Xiao Bao routines and push notifications were deployed but not executing. The web process also
ran two in-process polling tasks (mediation AI every 2 s, image jobs every 30 s), which stop
whenever the Eco dyno sleeps.

Running every process on Heroku Basic would cost about $28/month, or $14/month consolidated.
The target is $0–5/month without reducing functionality, reliability or privacy.

Every background queue already lives in MongoDB with leases, attempt limits, back-off and
duplicate guards, and each worker exposes a "process one item" function. Continuous execution was
an implementation choice; only time-based wake-ups (routines falling due, retry back-off, expired
leases, the inactivity auto-pause) are inherent.

## Decision

Adopt a lean serverless architecture on AWS (option A), reached incrementally through a hybrid
stage (option B):

- Two Lambda functions built from one source tree and dependency set:
  - **API:** FastAPI behind the Lambda Web Adapter on a response-streaming Function URL.
  - **Jobs:** a handler that processes available work and exits.
- One recurring EventBridge Scheduler schedule (every minute) invokes the jobs function. The API
  asynchronously invokes it after creating work.
- MongoDB collections remain the durable job queues and the single source of truth. No SQS, no
  per-routine AWS schedules, no third Lambda function.
- Existing MongoDB Atlas, S3 and Vercel stay as they are. OpenTofu provisions AWS resources.
- No API Gateway, SQS, NAT gateway, load balancer or continuously running compute unless a
  demonstrated requirement emerges.
- A scheduling delay of about one minute under normal operation is acceptable.

## Phase 1 design

### Job runner (`app/workers/job_runner.py`)

Every queue runs in its own lane, concurrently, and processes one item at a time:

| Lane | Queues | Why |
|---|---|---|
| Fast | Routine clock, push delivery | Never waits behind AI or image work. Keeps polling every 1–2 s while other lanes run, and makes a final pass when they finish. |
| Routine | Routine runs | Starts as soon as the clock pass has run, regardless of mediation or image work. |
| Mediation | Mediation AI | Independent of images and routines, as in the previous separate in-process task. |
| Image | Thumbnails, advent archiving | Sequential, which bounds CPU and storage load, as before. |

Further properties:
- **Two modes, shared logic.** Finite mode (with a deadline) drains the queues and returns.
  Continuous mode (with a stop event) keeps polling.
- **Bounded items.** Each item runs under a timeout inside its lease (push 45 s of 60 s; routine,
  mediation and image 240 s of 300 s). No item starts unless it fits before the deadline. An
  item that times out keeps its lease and is retried after it expires.
- **Failure isolation:**
  - A failing item is recorded and its queue backs off for the idle interval. Other queues are
    unaffected and the runner keeps going.
  - Each queue builds its dependencies lazily and independently (`_lazy_queue`). A queue that
    cannot initialize (for example a missing API key) fails only its own turns and is retried; it
    never disables the others.
- **Latency change from the previous production setup.** Image and mediation work keep their idle
  polls (30 s and 2 s) and still run independently of each other. Under Heroku nothing changes
  until the `worker` process is scaled. Under Lambda, routines materialize within about one
  minute instead of ≤15 s (approved).

### Routine latency, step by step

| Step | Mechanism | Bound |
|---|---|---|
| Materialize the due run | Clock pass in the fast lane | ≤15 s (`--loop`); next scheduled invocation, ≤ ~60 s (Lambda) |
| Start execution | Routine lane claims the run right after the clock pass | Immediate; independent of mediation and image work (tested) |
| Persist the message | The run generates and commits the inbox message | AI time, ≤240 s per attempt, 3 attempts with back-off |
| Deliver the push | Fast lane, polling while other lanes work | Seconds after the commit (≤2 s poll) |

### Other Phase 1 changes

| Area | Change |
|---|---|
| Entry points | `python -m app.workers.drain [--loop]` (local, Heroku). `app/lambda_jobs.py` (Lambda) keeps a persistent event loop, because Motor binds its client to one loop. Every invocation serves every queue. |
| Wake-ups | `app/services/job_wakeup.py`: `none` (default) or `lambda` (asynchronous `Event` invoke). Payload is `{"kinds": [...]}` only. Failures are logged by error type and never fail the request. |
| Configuration | `XIAOBAO_IN_PROCESS_JOBS_ENABLED`, `ENSURE_INDEXES_ON_STARTUP`, `MONGO_MAX_POOL_SIZE`, `JOB_WAKEUP_*`, `AWS_S3_REGION`, `LOG_FORMAT`. `IMAGE_WORKER_ENABLED` and `MEDIATION_WORKER_ENABLED` keep their meaning. |
| Indexes | `app/db/indexes.py` and `scripts/ensure_indexes.py` (deploy-time, idempotent). |
| Dependencies | Runtime set trimmed. Test and type-stub packages moved to dev. CI installs `--group dev`. |
| Containers | One `Dockerfile`, two arm64 targets sharing all dependency and source layers. |
| Heroku | Procfile: `web` plus `worker: python -m app.workers.drain --loop`. |

## Review fixes (2026-11-25)

### 1. Mediation job ownership

- **Claiming** sets a fresh `lease_token`. `mark_completed`, `mark_failed_or_retry` and
  `is_owner` match only `_id` + `status=PROCESSING` + the caller's token, so a superseded worker's
  writes match nothing.
- **Retry or fail** is decided atomically in one update pipeline (attempts vs `max_attempts`,
  defaulting to 3 for legacy documents). The token is removed on completion, retry and stale
  failure.
- **Ownership re-checks.** `MediationAIService` re-checks ownership after each slow external call
  (moderation, generation) and before any write. A superseded worker stops with
  `MediationJobSupersededError` and persists nothing.
- **Outputs at most once per job.** Reflections, advice and AI comments record `ai_job_id` and
  are written with insert-if-absent keyed on it. A late writer receives the stored output and
  never replaces it. The supporting indexes are sparse and non-unique, so legacy documents can
  never block startup.
- **Sanitized error storage.** A failed job's `error_message` stores the error type, not the
  exception text, which can contain provider response bodies.
- **Compatibility.** Pending legacy jobs are claimed normally. A processing legacy job (no token)
  cannot be completed by a token-less caller; it is recovered once its stale threshold passes.
- **Residual race.** Two writers persisting the same job's output within the same instant could
  both insert. That requires two simultaneous owners, which the token and re-check make
  practically impossible. A unique index would close it, but could fail startup if legacy
  duplicates exist, so it is deferred.

### 2. Worker isolation

One lane per slow queue, lazy per-queue dependencies and per-item failure handling, as described
above. Tests cover the following:
- a failing queue while a healthy queue drains;
- a queue that cannot initialize while another processes work, with its build retried;
- a hung item cut off at its timeout;
- a routine starting while mediation and image work are underway.

### 3. Logging and observability

- **Allowlisted fields.** `StructuredFormatter` renders an allowlist of `extra` fields (job
  kind, counts, durations, error type and code location, opaque routine and delivery IDs). Other
  fields are dropped, so content cannot leak through `extra`.
- **Formats.** Text by default; `LOG_FORMAT=json` (set in the images) emits one JSON object per
  line.
- **No exception text in job logs.** Job error logs carry `error_type` and `error_location`, but
  no exception message or traceback. Prompts, generated content and provider bodies therefore
  never reach job logs.
- **Run summary.** Every run ends with a `job_run_summary` event carrying per-kind
  `processed`/`failed`/`timed_out`, their totals, `duration_ms` and `outcome`. It is logged at
  WARNING when any item failed or timed out.
- **Alarm on the summary, not the invocation.** A Lambda invocation returns successfully even
  when items failed, because those items are retried by their queues. Phase 2 alarms therefore
  key on a CloudWatch metric filter:
  `{ $.event = "job_run_summary" && ($.failed_total > 0 || $.timed_out_total > 0) }`.

### 4. Routine latency

Documented above and in the README. Tested: routine execution begins and completes while longer
mediation and image items are still running.

### 5. AWS integration

- **S3 region.** S3 uses `AWS_S3_REGION`, falling back to `AWS_REGION`. On Lambda, `AWS_REGION`
  is reserved and holds the function's region, so Phase 2 must set `AWS_S3_REGION` explicitly.
- **Wake-up credentials.** The wake-up uses its own region (`JOB_WAKEUP_LAMBDA_REGION`) and
  optional invoke-only keys (`JOB_WAKEUP_AWS_ACCESS_KEY`/`_SECRET_KEY`). The existing S3 keys on
  Heroku are never extended with Lambda permissions, and the S3 path is unchanged.
- **Validation.** Half-configured key pairs are rejected at startup. Without keys, both clients
  use the default credential chain (the IAM role on Lambda).

### 6. Deployment on merge

- **Merging triggers a deploy.** Merging into `master` runs `.github/workflows/deploy.yml`:
  tests, then an automatic production deploy to the Heroku app `counting-down-fastapi`. Pull
  requests into `master` get no CI (`dev.yml` runs only for PRs into `dev`).
- **CI fix.** The test job installed runtime dependencies only. With `pytest-asyncio` and
  `pytest-cov` (which pulled in pytest) moved to the dev group, CI would have failed with
  `ModuleNotFoundError: pytest` and blocked every deploy. Both workflows now install
  `--group dev`; verified locally.
- **Unchanged infrastructure:** the same Heroku app, a single web dyno, no AWS resources, the
  same configuration variables and no database permission changes.
- **Changed application behaviour after the merge-triggered deploy:**
  - The web dyno runs image and mediation jobs through the new runner: same flags, same idle
    polls, separate lanes.
  - Mediation jobs are fenced by tokens; outputs are written once per job; stored job errors
    hold the error type only.
  - The Procfile's `clock` and `push-worker` types are removed (both at 0 dynos) and `worker`
    now runs the drain loop (also at 0).
  - Logs gain allowlisted structured fields, still in text format on Heroku.
  - Wake-ups are no-ops (`JOB_WAKEUP_MODE` unset).
  - Push enqueue races return the stored delivery instead of an error.
  - Indexes are still created at startup, now including the new sparse `ai_job_id` indexes.
  - Routines and push remain inactive until a worker runs, exactly as today.

## Amendments and status

| # | Requirement | Status |
|---|---|---|
| 1 | Verify Atlas network access; never broaden it without approval | **Open: Phase 2 gate.** Not verifiable from the repository. No Atlas setting is changed. |
| 2 | Rate limiting and AI safeguards before exposing the API through Lambda | **Phase 3 gate.** Xiao Bao chat has a per-user limit. Login brute-force protection, a mediation AI cap and a global AI spend guard are still to come. |
| 3 | Long jobs must not delay push or routines | **Done:** separate lanes, per-item timeouts. |
| 4 | Bounded async retries and event expiry | **Phase 2:** `maximum_retry_attempts = 0`, `maximum_event_age_in_seconds = 300` on the jobs function; the schedule target uses 0 retries and a 120 s event age. |
| 5 | Monitor async event age, dropped events and overdue jobs | **Phase 2:** alarms on `AsyncEventAge`, `AsyncEventsDropped`, `Errors` and `Throttles`; the `job_run_summary` metric filter; oldest-due push and routine age metrics. |
| 6 | Test crash recovery, expired leases, concurrent wake-ups, duplicates | **Done:** push, mediation and runner integration tests; existing routine and image tests. |
| 7 | No exactly-once push claim | **Done:** at-least-once, with best-effort dedupe (unique delivery per message and device, token fencing, service-worker `tag` with `renotify: false`). |
| 8 | Protect ECR images used by active and rollback versions | **Phase 2:** SHA tags; keep 5 Lambda versions; lifecycle policy expires only untagged images and SHA tags beyond the newest 10. |
| 9 | One image vs two build targets | **Resolved:** one Dockerfile, shared dependency and source layers, two thin targets. |
| 10 | Verify auth, cookies, CORS, SSE, disconnects and S3 before the API move | **Phase 3 gate:** checklist below. |
| 11 | Free allowances are shared with other projects | **Accepted:** a dedicated AWS account for BIBI is recommended; budgets apply in any case. |
| 12 | Infrastructure and CI must not compete over versions and aliases | **Phase 2:** Tofu ignores `image_uri` and the alias version; CI owns code updates, publishing and alias moves. |

## Known risks and deferred work

- **Push is at-least-once.** A crash between sending and recording can repeat a push.
- **Mediation output residual race** (see review fix 1); a unique index is deferred.
- **Image job errors** still store `str(error)[:500]` in `thumbnail_job.last_error` /
  `archive.last_error`. These are storage and processing errors, not user content. Sanitizing
  them is a small follow-up.
- **Non-job request paths** still use `logger.exception`, which includes exception messages.
  Reviewing them belongs with the Phase 3 API work.
- **No CI on PRs into `master`.** Add a pull-request trigger for `master` (recommended before
  Phase 2).
- **Phase 2 infrastructure** (async invoke configuration, alarms, metric filters, ECR protection)
  is designed but not provisioned.

## Phase 2 readiness criteria

Phase 2 may start only when all of the following hold:

1. PR #17 is reviewed, merged, and its automatic Heroku deploy is verified healthy: `/health`,
   mediation and image jobs processing, no new error events in the logs.
2. The Atlas network access list is confirmed by the owner, with a decision on how Lambda
   connects. Nothing is broadened without explicit approval.
3. The AWS account is chosen (a dedicated account in an Organization is recommended) and an
   OpenTofu state location is agreed.
4. A CI pull-request trigger for `master` is added, so infrastructure and application changes are
   tested before merge.
5. Phase 2 configuration values are agreed:
   - Lambda: `AWS_S3_REGION`, `LOG_FORMAT=json`, `ENSURE_INDEXES_ON_STARTUP=false`, and
     `MONGO_MAX_POOL_SIZE` around 5.
   - Heroku: `JOB_WAKEUP_MODE=lambda`, `JOB_WAKEUP_LAMBDA_FUNCTION_NAME`,
     `JOB_WAKEUP_LAMBDA_REGION`, and invoke-only `JOB_WAKEUP_AWS_*` keys.

## Phase 2 plan: background work on AWS (hybrid)

1. **OpenTofu module** (`infra/`), applied by the owner. State in S3 with native lock files.
   - ECR repository and lifecycle policy (amendment 8).
   - Jobs function (arm64, 512 MB, 900 s timeout, reserved concurrency 1), with a `live` alias.
   - Async invoke config (amendment 4).
   - One EventBridge schedule `rate(1 minute)` targeting the alias, plus its role.
   - SSM SecureString parameter names. Values are entered by hand and kept out of state.
   - Log group with 14-day retention and the `job_run_summary` metric filter.
   - Alarms (amendment 5) and an SNS email topic.
   - AWS Budget alerts at $2 forecast and $5 actual.
   - GitHub OIDC deploy role.
   - IAM user for Heroku limited to `lambda:InvokeFunction` on the jobs alias.
2. **CI workflow** on push to `master`, after tests:
   - build `jobs` for arm64 and push it tagged with the SHA;
   - run `scripts/ensure_indexes.py`;
   - update the code, publish a version, run a smoke test on the version, then move the alias;
   - prune versions beyond five.
3. **Jobs function:** read secrets from SSM at cold start; emit the oldest-due-work metrics.
4. **Heroku configuration:**
   - the wake-up values above;
   - `MEDIATION_WORKER_ENABLED=false`, `IMAGE_WORKER_ENABLED=false`;
   - no `worker` dyno.
5. **Verification in production with synthetic data:**
   - push test from a phone;
   - a one-off reminder two minutes ahead;
   - a daily routine end to end;
   - a mediation request;
   - a photo upload with its thumbnail;
   - a forced timeout, confirmed in the summary metric.
6. **Rollback:** set `JOB_WAKEUP_MODE=none` and re-enable the web flags. Optionally scale the
   Heroku `worker`.

## Phase 3 plan: API on Lambda

Preconditions: amendments 2 and 10 complete.

- **Compatibility checklist:**
  - `X-Session-Id` authentication and frontend cookie storage;
  - CORS for the Vercel origins (application-managed, not Function URL CORS);
  - SSE streaming through the Web Adapter, including time-to-first-token;
  - client disconnects mid-stream (the generation is persisted or cancelled cleanly);
  - multipart upload size limits;
  - image byte endpoints over 6 MB (prefer presigned URLs);
  - presigned S3 upload and download with the explicit bucket region;
  - push subscription flow;
  - cold-start latency.
- **Cutover:** API function with a streaming Function URL and reserved concurrency; set
  `VITE_API_BASE_URL` in Vercel (frontend PR #12). Heroku stays at zero dynos for a soak period,
  then is decommissioned only with explicit approval, and its static AWS keys are rotated and
  removed.

## Rejected alternatives

- **API Gateway HTTP API:** cannot stream responses and has a ~30 s timeout.
- **SQS:** duplicates the MongoDB queues.
- **One EventBridge schedule per routine:** a second source of truth for routine times.
- **A third Lambda function for push:** not needed; the fast lane already isolates push.
- **A single Heroku Basic dyno:** $7/month and keeps static AWS keys.
- **Google Cloud Run:** a second cloud provider.
- **A VPS:** operating-system maintenance.
