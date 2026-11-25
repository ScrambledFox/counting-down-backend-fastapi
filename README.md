# Counting Down - FastAPI

```
    ♥♥♥♥♥        ♥♥♥♥♥
  ♥♥♥♥♥♥♥♥♥    ♥♥♥♥♥♥♥♥♥
 ♥♥♥♥♥♥♥♥♥♥♥  ♥♥♥♥♥♥♥♥♥♥♥
♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥
♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥
 ♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥
  ♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥
   ♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥
     ♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥♥
       ♥♥♥♥♥♥♥♥♥♥♥♥
         ♥♥♥♥♥♥♥♥
           ♥♥♥♥
```

This repository contains the backend implementation of the Counting Down application (For my beautify wife Danfeng) using FastAPI. The application provides APIs to manage and retrieve flight information, todos, and messages.

## Boundaries & Agreements

The `/api/v1/relationship-care` API stores personal boundaries, requests, and growth goals
alongside shared, revisioned agreements. Personal content is editable only by its owner.
Growth goals are private by default and become visible to the partner only when their owner
explicitly shares them. An agreement becomes active only when both authenticated users accept
the same immutable revision; later edits create a new unaccepted revision while retaining the
agreed history.

MongoDB collections and indexes are created additively during application startup, so no
data migration is required. Optional synthetic local examples can be loaded idempotently:

```bash
uv run python scripts/seed_relationship_care.py
```

The seed script refuses to run when `APP_ENV=prod`.

## Xiao Bao (小宝)

The authenticated `/api/v1/xiaobao` API provides private, owner-scoped conversations with
streamed Responses API output. Every turn reloads an authorized subset of boundaries, wishes,
goals, agreements, incomplete Together List items, and bounded mediation history. Mediation
history contains lifecycle state, shared advice, and shared comments. The authenticated user's
own perspective/reflection is available only through an on-demand runtime lookup; the partner's
private content is never loaded. Photos, private messages, travel, and Advent records remain
outside the context boundary.

A single shared relationship profile stores the couple's usual setup, current visit state,
locations, time zones, practical constraints, and general personality/preference notes. Both
authenticated users can read and edit it through `GET`/`PUT /api/v1/relationship-profile`.
Xiao Bao reloads the profile before every turn and prioritizes remote-friendly suggestions when
the profile says the couple is long-distance and currently apart. The first-read defaults are
editable and are not written to MongoDB until one of the users saves the profile.

Xiao Bao runs a bounded LangGraph tool loop. Relationship records are supplied through runtime
context and are not copied into graph checkpoints. Provider calls use `store=False`; application
messages remain the source of conversation history. Human review is persisted as proposal state,
not as a paused graph. A shared-agreement acceptance creates a private draft, and the existing
agreement workflow remains the only way to propose it to the partner.

Final replies use a strict `{content, mood}` structured envelope in the same Responses API call.
Only decoded Markdown content is streamed to clients. The persisted nullable mood is limited to
`IDLE`, `LOVE`, or `CONCERNED`; greeting, thinking, success, and sleep remain browser-owned states.

Mediation actions are always reviewable proposals. Xiao Bao can start a session, post a moderated
shared comment clearly authored as Xiao Bao, or save the current user's private perspective draft.
It cannot submit a perspective, resolve a mediation, or archive one. Shared comments never use
private mediation context and do not trigger recursive mediation-assistant replies.

Set `OPENAI_API_KEY` to enable generation. The model, limits, context budget, and checkpoint TTL
are configurable through the `XIAOBAO_*` and `OPENAI_MODEL_XIAOBAO` values documented in
`.env.example`. MongoDB collections and indexes are added on startup without a data migration.

### Xiao Bao routines

Owner-private routines and reminders are managed below `/api/v1/xiaobao/routines`; their messages
appear in `/api/v1/xiaobao/inbox`. A `ROUTINE` is LLM-generated and uses a `DAILY` or `WEEKLY`
schedule. A `REMINDER` uses `ONCE` plus an IANA timezone, `YYYY-MM-DD` local date, `HH:MM`
wall-clock time, and exact user-approved static text; it never loads relationship context or calls
the model when delivering. A nonexistent daylight-saving local time is rejected for a reminder so
the reviewed time remains truthful; recurring routines retain their forward-to-the-next-valid-time
behavior. Weekdays are integers from Monday `0` through Sunday `6`. Event-based
`TRIGGER` scheduling is intentionally not supported yet and must not be represented as a calendar
schedule. A proposed routine or reminder remains a review card until its owner accepts it.

Routine execution uses two durable Mongo-backed queues, a clock that materializes due occurrences
and a worker step that executes them. Both run inside the consolidated background job runner
described under [Background jobs](#background-jobs).

The clock materializes uniquely keyed occurrences and advances schedules atomically. The worker
claims runs with expiring leases and bounded retry backoff. It rebuilds fresh relationship-care
context, including incomplete non-deleted Together List items, but it never queries mediation,
loads chat history, reuses an interactive checkpoint, or exposes model tools. Consequently an
unattended routine can read the Together List for relevance but cannot change it or any other
relationship data. Configure polling, lease, retry, and batch limits with the
`XIAOBAO_ROUTINE_*` values in `.env.example`.

The clock auto-pauses an active routine when that routine has output that has been visible and
unread in its owner's routines inbox for five consecutive full days (exactly 120 hours).
Visibility begins when a staged message first becomes
`COMPLETE`; finalize retries preserve that original delivery time. Older visible records created
before delivery timestamps were stored use `created_at` as a safe legacy fallback. Hidden
`PENDING_DELIVERY` messages, ordinary Xiao Bao chat, another owner's inbox, and another routine's
messages never qualify. The clock re-checks the exact unread predicate immediately before its
revision-guarded pause; a read observed by that check prevents the pause, while a concurrent read
after the check does not undo the already observed inactivity decision.

Routine responses expose `pause_reason` as `MANUAL`, `UNREAD_INACTIVITY`, or `null`, alongside
`paused_at`. Resuming an inactivity-paused routine returns `409 Conflict` while that same routine
still has output at or older than the unread threshold. Reading those older inbox messages permits
resume and clears both pause fields; manually paused routines are unaffected by this guard.
The private inbox accepts optional `routine_id`, opaque `cursor`, and `limit` query parameters so
all blocking output remains reachable. A routine filter is owner-validated, pages use a stable
newest-first `(created_at, id)` order, and `next_cursor` retrieves the next older page without
timestamp ties being skipped. `unread_count` remains the owner's global inbox count.

Pause, resume, edits, and deletion increment the routine revision, invalidating any older claimed
run. Delivery uses a Mongo-backed guard on that revision. A generated message is first stored as
`PENDING_DELIVERY`, which inbox queries never return; it becomes visible only after the routine
record atomically commits that run ID while still enabled at the same revision. If pause/resume
wins that ordering race, the staged message is explicitly deleted. If commit wins, the delivery
is considered to have happened before the later pause; a durable commit marker lets a retry
finish exposing the non-expiring hidden message after a worker crash or arbitrary downtime, even
when the routine is later paused or edited. The marker blocks later deliveries for that routine
until the committed message is visible, then it is released idempotently. This provides a clear
ordering without assuming transactions across the routines and messages collections.

### Xiao Bao Web Push

Web Push is disabled by default. When configured with the `XIAOBAO_WEB_PUSH_*` VAPID and
subscription-encryption values, browsers can register an authenticated device at
`/api/v1/xiaobao/push/subscriptions`. Subscriptions are encrypted at rest and list responses never
expose endpoints or encryption keys. The background job runner delivers a fixed encrypted
payload containing only an inbox message identifier; the frontend service worker owns the generic
lock-screen text and navigation. Inbox persistence remains authoritative: a completed private inbox
message is queued for push afterward, and push errors never retry generation, alter read state, or
remove that message. Existing messages are never backfilled when push is enabled.

Live-model checks are opt-in and use synthetic content:

```bash
RUN_XIAOBAO_LIVE_EVALS=1 uv run pytest -m live_ai tests/live/test_xiaobao_live.py
```

## Background jobs

All background work lives in durable MongoDB queues with leases, attempt limits and duplicate
guards: the routine clock, routine runs, Web Push delivery, mediation AI and image processing. One
runner (`app/workers/job_runner.py`) calls each queue's single-item function. Stopping it at any
point is safe: an interrupted item keeps its lease and is retried after the lease expires.

```bash
python -m app.workers.drain            # process available work, then exit
python -m app.workers.drain --loop     # keep polling (local development, Heroku `worker`)
python -m app.workers.drain --kinds push,clock --max-seconds 120
```

Every queue runs in its own lane, concurrently, one item at a time per queue: the clock and push
share a fast lane, and routine runs, mediation and image processing each have their own. A slow
or failing queue never blocks another one, and a queue whose dependencies cannot be built (for
example a missing API key) fails only its own turns and is retried after its idle interval.

Mediation jobs are fenced by a claim token: only the current owner can complete, fail or retry a
job, ownership is re-checked after each slow external call before anything is persisted, and AI
outputs (reflections, advice, AI comments) are deduplicated per job on a best-effort basis until
a unique index is introduced (see the ADR).

Push delivery is at-least-once: a crash after a push is sent but before it is recorded can repeat
it, and the service worker collapses repeats through the notification tag.

### Routine latency

A routine passes through four steps, each with its own bound:

| Step | What happens | Typical delay |
|---|---|---|
| Materialize | The clock turns a due routine into a run | Next clock tick: within 15 s in `--loop` mode; within ~1 minute when a scheduler invokes the runner |
| Start | The routine lane claims the run | Immediately after the clock pass; never waits for mediation or image work |
| Persist | The run generates and commits the inbox message | AI generation time, capped at 240 s per attempt (300 s lease) |
| Deliver | Push delivery sends the notification | Seconds: the fast lane polls every 1–2 s while other lanes work |

### Logs

Structured fields (job kind, counts, durations, error types and code locations, opaque IDs) are
rendered from an allowlist, as `key=value` text or, with `LOG_FORMAT=json`, one JSON object per
line. Job logs never include exception messages, prompts, generated content or provider
responses. Each run ends with a `job_run_summary` event carrying `processed_total`,
`terminal_total` (expected outcomes such as revoked push subscriptions), `failed_total`,
`timed_out_total` and `duration_ms`. The run itself succeeds even when items fail,
so alert on those fields.

The web process can also work on queues itself, controlled by `IMAGE_WORKER_ENABLED` (default on),
`MEDIATION_WORKER_ENABLED` and `XIAOBAO_IN_PROCESS_JOBS_ENABLED` (clock, routines and push). When
`JOB_WAKEUP_MODE=lambda`, the API asynchronously invokes `JOB_WAKEUP_LAMBDA_FUNCTION_NAME` after
creating work; the wake-up carries queue names only and is a hint, since scheduled runs pick up
anything it misses.

`app/lambda_jobs.py` is the AWS Lambda entry point. The `Dockerfile` builds two arm64 targets from
the same dependency and source layers: `api` (uvicorn behind the Lambda Web Adapter, streaming) and
`jobs` (the Lambda handler). See `docs/adr/0001-serverless-background-jobs.md`.

## Database indexes

Indexes are idempotent. They are created at web startup unless `ENSURE_INDEXES_ON_STARTUP=false`,
in which case run them once per deploy:

```bash
python scripts/ensure_indexes.py
```

## Seeding airports

Flights reference airports by their ICAO code, so the `airports` collection
must be populated before flights can be created. A curated dataset of ~7.6k
commercial airports (those with both an ICAO and IATA code) is committed at
`app/data/airports.json`.

To load it into MongoDB (uses the same `MONGO_URL` / settings as the app):

```bash
python scripts/seed_airports.py
```

The script is idempotent — it upserts by ICAO code, so it is safe to re-run
(re-runs report `inserted=0`). The required indexes (unique ICAO, IATA, and a
text index for search) are also created automatically on app startup.

## Flight metadata lookup (AeroDataBox)

The `GET /api/v1/flights/lookup?flightNumber=KL123` endpoint proxies flight
metadata requests to [AeroDataBox](https://rapidapi.com/aedbx-aedbx/api/aerodatabox)
via RapidAPI. When a user clicks "Lookup flight" in the frontend, the backend
fetches candidate flights for the next `AERODATABOX_LOOKUP_WINDOW_DAYS` days
(default: 7), normalises the response into a provider-independent DTO, and
returns up to N candidate flights for the user to choose from.

### Required environment variable

```
AERODATABOX_API_KEY=<your_rapidapi_key>
```

Subscribe at https://rapidapi.com/aedbx-aedbx/api/aerodatabox. The free plan
allows ~150 calls/month — the built-in cache (see below) makes this viable for
personal use.

### AeroDataBox endpoint used

```
GET /flights/number/{flightNumber}/{dateFrom}/{dateTo}
```

- `dateFrom` / `dateTo` are ISO 8601 local dates (`YYYY-MM-DD`).
- A 404 response means no flights found; this is treated as an empty result, not an error.
- The backend accepts either a bare array or `{"flights": [...]}` response shape.

### Caching

Lookup results are cached in-process (a module-level dict) to minimise API calls:

| Scenario        | TTL env var                               | Default |
|-----------------|-------------------------------------------|---------|
| Results found   | `AERODATABOX_CACHE_TTL_SUCCESS_SECONDS`   | 6 h     |
| No results      | `AERODATABOX_CACHE_TTL_NO_RESULTS_SECONDS`| 30 min  |
| Provider error  | not cached                                | —       |

The cache is process-local. Restart the server to clear it.

### Known limitations

- Flight number alone is ambiguous. Multiple candidates are returned and the user must select one.
- ICAO codes are not always available from AeroDataBox for smaller airports; those fields will be empty and the user must fill them manually.
- The free AeroDataBox plan provides ~150 calls/month.
- The cache is not shared across multiple server instances.
