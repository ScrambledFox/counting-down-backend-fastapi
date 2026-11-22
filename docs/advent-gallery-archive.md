# Advent gallery archive

The current year's gifts stay on the advent calendar. A year's gifts become eligible
for the shared gallery at 00:00 UTC on December 26, independently of opened-day state.
Eligibility derives from the gift's existing UTC upload timestamp.

## Processing

An image worker starts as an independent application lifespan task. It checks for work
on startup and after 30 idle seconds. It does not block startup or gallery requests.
No separate paid scheduler or worker dyno is required. Sleeping/offline applications
catch up on their next startup.

Each advent document carries an `archive` job. Missing state means pending; claims
atomically assign a token and five-minute lease. A job has a two-minute timeout.
Failures persist an error, attempt count and exponential retry time (30 seconds to
one hour). Expired leases can be reclaimed after a crash. Completed gifts are excluded.

The worker prepares standard thumbnails before publishing new gallery metadata.
It reuses the source image and metadata ID; reconciliation also recognises an existing
gallery image with the same image key. Insert-only metadata preserves titles, tags,
dates, uploader and soft deletions. Deleting a gallery picture does not remove the
advent source or cause a later archive pass to restore the picture.

Tags include `advent`, the year, `advent-2025-day:22`, the gift type, and `sensitive`
for spicy/hot gifts. The source ID is recorded as `source_advent_id`.

Existing gallery images, including previously imported advent gifts, are reconciled
by durable `thumbnail_job` leases. Existing thumbnails are checked and reused in the
worker. Original bytes are downloaded only if a required thumbnail is missing.
`thumbnail_sizes_ready` records completed sizes. Explicit thumbnail requests persist
requested sizes; a request arriving during processing remains eligible afterward.
Image processing is sequential and CPU thumbnail creation runs outside the event loop.

## Gallery reads

Gallery listing, filtering, pagination and metadata reads do not import advents,
write job state, check S3 existence, download originals or generate thumbnails.
Ready thumbnails receive signed URLs; unready thumbnails return null.
The frontend uses available previews or a placeholder, polls metadata with backoff
capped at 30 seconds, and cancels polling when unmounted. Only opening a picture
downloads its full-size original. Uploads are queued for the same durable worker.

The thumbnail byte endpoint used by the advent calendar retains its existing
on-demand behaviour. This is separate from the gallery metadata request path.

## Operations and validation

- `IMAGE_WORKER_ENABLED` defaults to true; set false to pause background processing.
- `IMAGE_WORKER_POLL_SECONDS` defaults to 30 and must be positive.
- Disabling the worker leaves already published pictures readable and jobs recoverable.
- Inspect `archive` on advents and `thumbnail_job` on gallery metadata for retries/errors.
- Existing imported records require no destructive migration; the worker backfills readiness.
- Tests cover date boundaries, atomic claims, expired leases, stale owners, retries,
  partial publication, late gifts, deletions, existing-image reconciliation, and custom requests.
- A full 12-picture page is tested to require one paginated metadata read, zero archive
  writes and zero S3 existence/download/upload operations. URL signing remains local.
- Compare warm production response times at the same page size after the initial
  backfill. The operation-count tests are not a substitute for measured network latency.
