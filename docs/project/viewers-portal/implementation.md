# Series Library Implementation and Verification

Status: implemented in this checkout; not deployed by this task.

Related discussion: [Media preparation performance and 4×/8× targets](media-preparation-performance.md).

## Components

- `episode_library.py`: SQLite-backed episode/job state, selection revisions, legacy migration, retained sources, quotas, one fair preparation worker, and shared viewer/admin operations.
- `app.py`: library lifecycle/snapshots and stale-event rejection; existing media processing runs in an isolated encoder runtime so it cannot replace live playback.
- `static/library.js`: multi-file upload review/queue, host episode management, participant read-only list, explicit selection/Next confirmation and deletion confirmation.
- Admin backend/UI: library-aware media deletion and per-episode controls using the same service.
- `tests/test_episodes.py`, `tests/library.test.cjs`: feature coverage alongside the existing playback, upload, admin and cache tests.

## Operational behavior

One process/worker is supported. The scheduler runs one preparation at a time globally. Ordering is fair between rooms and favors upcoming episodes within a room. It does not preempt a running encoder.

`admin.sqlite3` contains episode and selection records. Queued jobs persist; interrupted running jobs become failed/partial and require Retry. A retry uses a new generation/asset ID and the retained source. Retrying the active episode clears selection and pauses the room; other episodes are unaffected.

New uploads never auto-select or remove prior episodes. The legacy `/api/upload` endpoint in a running server also adds to the library; `/api/media` deletes the selected episode. Media delivery remains scoped to the authenticated room and selected asset. Switching updates the episode ID, persistent selection revision and playback revision; clients include these in readiness/control events.

Room/server quotas include sources and generated files. Upload writes check capacity before writing; encoding is checked every 250ms and cancelled when a quota/free-space threshold is crossed. Some output may be written between samples. Failed cleanup remains visible and retryable. Sources are intentionally retained to support retries; account for this in storage planning.

The existing active movie is imported once on startup, preserving its directory and `current.json`. Library selection is authoritative after migration. Compatible older readers can still see the current manifest, but older releases do not understand the full library or its deletion rules. Back up the complete volume before any rollback.

## Verification

Local Python/JavaScript tests cover role enforcement, cross-room isolation, eight retained episodes, rename/order persistence, explicit selection, stale event rejection, generation retry, restart state, fair single-worker scheduling, confirmation gates, quota rejection and deletion failures. Docker additionally runs real audio/video FFmpeg tests, including eight uploads, early-playable segments and deletion during conversion.

Browser QA used an isolated Docker preview with generated clips. Verified host sign-in, no implicit selection, explicit first selection, manual Next, selection badges, previous episodes remaining in the library, confirmation dialogs, no browser console errors and a 375px viewport without horizontal overflow.

Production-sized 2.5-hour files, real mobile-network playback, staging acceptance and deployment remain operational checks. The preview uses short generated fixtures and does not establish conversion throughput for a production movie.
