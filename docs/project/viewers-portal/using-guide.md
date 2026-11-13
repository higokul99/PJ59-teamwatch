# User Guide: Watching a Series in One Room

**Status: implemented in this checkout; not deployed by this task.** After deploying this version, each room retains its episodes. Uploading another episode does not select it or delete the previous episode. Existing active media is imported into the library automatically on startup.

Date: 13 November 2026. See the [requirements](prd.md) and [screen design](ui-design.md).

## Host: add the series

1. Join the existing room with your host passcode.
2. Open Episode library and choose Add episodes.
3. Select the eight episode files. Check their titles and order; rename or reorder them if filenames are unclear.
4. Check available storage, then start the upload queue.
5. Keep the tab open while files transfer. Uploads run one at a time, and accepted files prepare on the server in the background.

If you close the page, files that have not finished uploading may need to be selected again. Completed uploads remain in the library.

## Understand progress

**Uploading** means bytes are still moving from your device to the server. **Queued** means the upload is stored and waiting for a preparation slot.

**Partly ready** means a portion of the episode is processed. For example, “Prepared through 00:12:30 / 00:45:00” means the first 12 minutes 30 seconds are prepared, not that preparation will finish in 32 minutes 30 seconds. That remaining duration is movie content, not an estimated waiting time.

You may start a partly ready episode, but playback may pause if it catches up with preparation. Wait for **Fully ready** if you want all server processing completed before the screening.

Full preparation does not mean every participant has downloaded or buffered the episode. Check connected-device readiness too; network/device buffering can still occur.

## Start watching

1. Select a playable episode from the library.
2. Tell participants to join the same room and tap Connect playback.
3. Review preparation and device readiness.
4. Press Play for everyone. Participants follow the shared timeline using their selected audio/video mode.

While watching, the host can add more episodes. Those uploads must not replace the active episode.

## Move to the next episode

1. Press Next episode, or select another playable episode from the list.
2. Confirm the switch. The room pauses and starts the selected episode at 00:00.
3. Participants remain in the room, but readiness resets while their devices load the new episode.
4. Wait for devices to be ready, then press Play.

If Next is disabled, check whether the next episode has enough prepared content. If none follows, the series is finished. Automatic episode advancement is not part of the initial release.

## Participant workflow

Join with the room code and your participant passcode. View the episode list to see what is coming next, but follow the host's selection. Use the existing Play/Pause permissions and Connect playback button. Selecting, uploading, reordering and deleting episodes are host/admin actions.

## Manage storage

Delete an individual episode from its menu when it is no longer needed. Deleting the currently playing episode stops the room for everyone. Deleting the whole library requires typing `CONFIRM`; it does not delete room accounts.

Deletion is permanent unless an administrator has a separate backup. Do not delete files merely to troubleshoot buffering.

## If something goes wrong

- Upload failed: check the connection, file size and quota, then retry that file.
- Preparation failed: read the error and retry when available. The host may need to upload a supported source again; other episodes remain intact.
- Playback approaches the prepared limit: pause and allow more preparation, or wait for Fully ready.
- Device is buffering despite full preparation: check its connection, reconnect playback or use audio-only mode where appropriate.
- Server restarted: rejoin if your session ended. The library should return, but playback starts paused and interrupted preparation must recover or report a retry requirement.
- Cleanup failed: follow the displayed retry guidance or contact the administrator; do not assume all files were deleted.


## Setup and storage settings

Run the app with a single Uvicorn worker, or rebuild and restart the Docker service using the project's deployment procedure. No manual database migration is required. Back up the complete data volume before deployment.

Optional settings in `.env` (Compose loads them; export them explicitly for a plain Python invocation):

```dotenv
ROOM_STORAGE_MB=51200
SERVER_STORAGE_MB=204800
MIN_FREE_DISK_MB=512
```

Values use MiB. The existing `MAX_UPLOAD_MB` still limits each file. Sources and generated media both consume storage. Interrupted preparation can be retried from its retained source. Retrying the currently selected episode pauses the room and clears the selection; select it again once playable. A failed upload may need to be selected again in the browser; remove its failed library entry when no longer needed.
