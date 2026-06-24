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

