# UI Design: Series Library and Episode Readiness

- Status: MVP implemented locally; design retained as the behavior reference
- Date: 13 November 2026
- Scope: [MVP PRD](prd.md)

## Design principles

Keep the current movie player and room identity familiar. Add a library beside the player on desktop and below it on mobile. Distinguish three independent signals: uploaded to server, prepared by server, and ready/downloaded on this device. Do not label partially prepared content as fully ready or promise lag-free playback.

## Room layout

1. Room heading: room code/name and active episode title.
2. Player: existing video/audio mode controls and timeline.
3. Active-episode readiness: prepared range and remaining preparation.
4. Room controls: existing playback controls, plus host-only episode selection and Next episode.
5. Episode library: ordered entries, upload queue and host management actions.

The library is visible to participants, but management actions are host-only. Admin management should use the same terminology in its own portal.

## Episode entry

Show episode number, editable title for hosts, duration, status label and active-selection badge. Identify the active episode with text and an icon, not color alone.

Example:

```text
02  The Arrival                         PARTLY READY
Prepared through 00:12:30 / 00:45:00 · 27.8%
[progress bar]
[Select episode] [More actions]
```

Host actions: Select episode, Rename, Move up, Move down, Retry preparation and Delete. Show only relevant actions. Provide buttons for ordering even if drag-and-drop is added later.

## State presentation

- Uploading: “Uploading to server · 42%”. This is transfer progress, not movie readiness.
- Queued: “Waiting for preparation”. Show queue position where reliable; do not invent an ETA.
- Preparing: “Preparing first playable segments”. Selection is disabled until playable.
- Partly ready: “Prepared through 00:12:30 of 00:45:00”. Explain that playback may pause beyond this point.
- Fully ready: “Entire episode prepared”. Still display device readiness separately.
- Failed: show a short, actionable error and Retry where supported. If a partial version is playable, show its prepared range beneath the error.

For the active episode, show prepared time ahead of the authoritative room position. When that margin reaches 30 seconds or less, display: “Playback is approaching the prepared limit. Pause and wait, or start after full preparation.” Do not imply that a stall is certain.

## Upload flow

The host chooses Add episodes, selects multiple files and reviews their proposed titles/order. Display quota usage and upload limits before transfer starts.

A queue lists each file independently with Waiting, Uploading, Uploaded or Failed transfer state. One transfer runs at a time. Completed uploads appear in the library and enter the server preparation queue. Leaving the page may interrupt uploads, but already accepted preparation jobs continue.

Do not switch the active episode when an upload finishes. If the library was empty, offer Select episode once the first episode becomes playable.

## Switching and Next

Selecting another playable episode opens a confirmation:

“Switch to Episode 2? Playback will pause and restart at 00:00 for everyone. Participants will stay in this room.”

Actions: Cancel / Switch episode.

During the request, disable duplicate submission. After success, update the player and active badge from server state; show “Episode selected. Wait for devices to connect, then press Play.” A failed request keeps the current episode selected.

Next episode uses the same switch behavior. If the next episode is queued or preparing, show its status and explain why Next is disabled. The last episode displays “End of series”. MVP has no autoplay toggle.

## Deletion

For an inactive episode: confirm its title and permanent removal.

For the active episode: explicitly state that everyone's playback will stop. Do not silently advance to another episode after deletion.

For the whole library: require typing `CONFIRM`; disable the submit button until it matches. The server must validate it too. Explain that room membership and accounts remain intact.

Show deletion progress and distinguish a completed deletion from a cleanup failure requiring retry.

## Accessibility and mobile

- Support a 375px viewport without page-wide horizontal scrolling.
- Use stacked episode cards on mobile; keep long titles wrapped or truncated with an accessible full name.
- Give icon buttons accessible labels and visible keyboard focus.
- Restore focus after dialogs; Cancel and Escape must dismiss without changes.
- Label progress bars and provide equivalent duration text.
- Announce state transitions politely; avoid announcing every playback tick or percentage update.
- Preserve keyboard focus and open dialogs during live updates.
- Respect reduced-motion preferences and use text alongside status colors.

## Empty, reconnecting and error states

- Host empty state: “Add episodes to build this room's series.”
- Participant empty state: “Your host hasn't added an episode yet.”
- Reconnecting: preserve the last visible state but mark it stale; disable destructive actions until refreshed.
- Quota reached: explain the limit and let the host remove content or ask the admin for capacity.
- Full server disk: pause acceptance of new work and show an actionable error; never hide existing content.
