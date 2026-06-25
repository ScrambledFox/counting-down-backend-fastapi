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

