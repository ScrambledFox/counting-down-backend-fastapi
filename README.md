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

Live-model checks are opt-in and use synthetic content:

```bash
RUN_XIAOBAO_LIVE_EVALS=1 uv run pytest -m live_ai tests/live/test_xiaobao_live.py
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
