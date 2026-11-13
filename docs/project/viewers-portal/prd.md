# PRD: Room Series Library and Episode Queue

- Product: TeamWatch — Viewers Portal
- Status: MVP implemented locally; pending deployment and staging acceptance
- Date: 13 November 2026
- Delivery: MVP first; autoplay in a later phase
- Related documents: [UI design](ui-design.md), [User guide](using-guide.md), [Technical interview notes](technical_doc_for_interview.md)

## Problem

A host wants to watch an eight-episode series with participants in one room. TeamWatch currently retains one active media file per room. Uploading a replacement switches playback when the first segments become available and deletes the previous movie's server files. This cannot support an uploaded series or a reusable episode playlist.

## Goal

Let hosts upload, retain, organize, prepare and select multiple episodes without recreating the room or making participants rejoin. Make preparation progress understandable before the group starts watching.

Server preparation is not a guarantee of uninterrupted playback: device readiness, download speed and network conditions remain separate concerns.

## Users and permissions

- Host: upload, rename, reorder, select, retry preparation and delete episodes in their room.
- Participant: view the episode list and readiness, follow the host-selected episode, and use existing participant playback permissions. Participants cannot change the active episode or library.
- System admin: inspect and manage any room's library through the admin portal. The same authorization and cleanup rules apply.

All checks must be enforced on the server, including media URLs and WebSockets.

## MVP requirements

### Upload and library

- Accept a multi-file selection, including at least eight episodes when configured storage limits permit.
- Upload one file at a time per browser queue. Show each filename, transfer percentage and any failure.
- Save each episode under an immutable ID; uploading another episode must not delete or select existing content.
- Let the host edit titles and episode order. Filenames can suggest titles, but must not be trusted as paths or definitive episode numbers.
- Treat transfer and preparation as separate states. An upload failure must not prevent the host from retrying that episode or continuing other queued files.
- Persist completed uploads, metadata, ordering and preparation jobs across application restarts. Browser-side files not yet uploaded must be reselected after the tab closes; resumable transfers are outside MVP scope.

### Preparation

- Use a server-wide preparation queue. Initially allow one running FFmpeg preparation job across rooms; tune concurrency after measuring server capacity.
- Prioritize the selected episode's queued job, then upcoming episodes, without interrupting a running conversion. Schedule fairly across rooms so one library cannot starve others indefinitely.
- Expose Queued, Preparing, Partly ready, Fully ready and Failed states, alongside Uploading where applicable.
- Show prepared duration, total duration and percentage. Count only complete, published segments across all required tracks.
- Preserve the existing early-playback approach: an episode becomes selectable for playback once a sufficient initial portion is published. The existing eight-second target is a starting policy, not a promise of eight-second processing time.
- If preparation fails after partial publication, retain the usable portion and clearly mark it incomplete. Retrying must not disrupt another episode's playback.

### Selection and playback

- Maintain exactly one active episode per room while retaining all other library entries.
- Switching requires host/admin authority. It pauses the room, resets position to zero, advances the playback revision and clears device readiness.
- Broadcast the active episode ID and updated timeline together. Participants load the selected episode without rejoining the room.
- Ignore delayed control/readiness messages belonging to a previous episode or revision.
- Provide a host-controlled Next episode action. Disable it with an explanation when no next episode exists or it is not yet playable.
- Switching does not automatically start playback. The host connects playback, checks device readiness and starts the room.

### Storage and deletion

- Enforce configurable per-file, per-room and server storage limits. Account for original uploads, generated segments and in-progress work; compressed upload size alone is insufficient.
- Provide confirmation for single-episode deletion. Deleting an active episode additionally warns that playback will stop for everyone.
- Require typed `CONFIRM` to delete the whole series/library. Keep the room and accounts intact.
- Stop relevant jobs, revoke media access, update room state and clean files safely. Report cleanup failures and allow retry; never report success while files remain unexpectedly accessible.
- Prevent cross-room access and deletion, even if an episode ID is known.

## Out of scope for MVP

- Autoplay, adaptive bitrate ladders, recommendations and cross-room shared libraries.
- Seamless gapless episode transitions.
- Guaranteed offline playback or resumable uploads after closing the browser.
- Unlimited storage or a promised conversion time for arbitrary files.

## Acceptance criteria

1. Upload eight valid episodes within quota; all remain listed and stored after preparation.
2. Watch episode 1 while episode 2 prepares; neither its upload nor preparation changes episode 1's playback timeline.
3. Select episode 2; all connected participants remain in the room, switch to its media, and reset readiness and position.
4. Delayed messages from episode 1 cannot alter episode 2's readiness or timeline.
5. A participant cannot upload, reorder, select or delete episodes through direct API calls.
6. A failed episode can be retried without removing other episodes.
7. After restart, the library/order/active selection are restored, playback starts paused, and interrupted jobs are reconciled without duplicate workers.
8. Storage-limit and disk-full failures are visible; existing playable content remains available.
9. Deleting an active episode stops playback; deleting the library requires exact server-validated confirmation.
10. Host and participant flows work at a 375px viewport with keyboard-accessible controls and readable status text.

## Rollout and measurement

Migrate the existing active movie to the first library record without moving or deleting its media. Test against a backed-up volume and preserve old-reader compatibility until the rollback plan is verified. Release behind an explicit configuration flag if necessary.

Measure time from upload completion to first playable media, preparation throughput, queue waiting time, conversion failures, peak storage and stalls near the prepared limit. Establish performance targets using staging tests with the actual long movie and server hardware.

## Later phase: autoplay

Opt-in autoplay should advance only after authoritative end-of-episode detection, sufficient preparation of the next episode and readiness from participating devices. Disconnected or unready devices need a documented policy before enabling this behavior. Manual Next remains available.


## Implementation notes

The local implementation uses `episode_library.py` for persistence, fair scheduling, quotas and episode operations. Durable job state/generation is stored on each episode record in `admin.sqlite3`, alongside a separate `episode_selection` table. A separate job table is not required for the one-worker MVP. Each episode retains its source so failed preparation can be retried; deletion removes both source and output.

Viewer controls are implemented in `static/library.js`. Admin Media library cards expose per-episode selection, rename, reordering, retry and deletion through the same service. Existing `/api/upload` clients add episodes in a running application; uploads no longer implicitly select or replace content. The current-selection manifest is maintained for compatible older readers, but older admin cleanup code is not library-aware: back up the volume before an upgrade or rollback.

Preparation quotas are checked throughout uploads and every 250ms during encoding. FFmpeg may write additional bytes between checks; the free-disk reserve is a safeguard, not an exact byte-perfect boundary. Initial defaults are 50 GiB per room, 200 GiB server-wide and 512 MiB free-disk reserve, configurable through environment variables. Completed source files count toward usage.

Autoplay, resumable uploads, adaptive bitrate and distributed workers remain outside this release. A restarted in-progress preparation becomes explicitly failed/partial and can be retried; queued accepted uploads resume automatically. See [implementation and test notes](implementation.md) for verification and operational limits.
