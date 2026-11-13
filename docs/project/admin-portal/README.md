# TeamWatch admin portal

The admin SPA is served at `/admin` (also `/admin/…`) by the same FastAPI service as the viewer portal. Its JavaScript and styles live in `static/admin/`; all administration calls use the dedicated `/api/admin` router in `admin_portal/backend/routes.py`.

## Module layout

```text
admin_portal/
  backend/
    __init__.py      # Registration with the main app
    routes.py        # APIRouter, SPA delivery and HTTP/WebSocket handlers
    service.py       # Persistence, room/account operations and shared-state queries
    schemas.py       # Request validation
    dispatch.py      # Viewer routing to isolated rooms
    cli.py           # Password initialization/recovery
  __main__.py        # python -m admin_portal
static/
  admin/             # Admin SPA, served by the shared /static mount
  ...                # Viewer SPA and assets
```

`app.py` registers the package with `install(...)`; it contains no admin endpoints or admin asset paths. The registration function builds an `APIRouter` with an injected service, installs room dispatch, and serves the admin entry page. All assets use the existing `/static` mount; legacy `/admin-assets/` file URLs redirect to `/static/admin/`. The folder uses an underscore to support ordinary Python imports. The existing viewer/media runtime remains in `app.py`; this change separates the admin module without rewriting the viewer architecture. Removing admin registration also removes its multi-room dispatcher, so a standalone deployment would need an explicit interface to the viewer service.

## Start and sign in

From the TeamWatch project directory, install the existing requirements and initialize the admin password:

```sh
python3 -m pip install -r requirements.txt
python3 -m admin_portal set-password
python3 -m uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
```

Open `http://127.0.0.1:8000/admin`. Sign in as **hellometora@gmail.com** using the password you entered. Passwords must contain 8–16 characters, including an uppercase letter, lowercase letter, number, and special character. There is no default admin password. Until a password is configured, admin login returns 503.

For Docker, after starting the service:

```sh
docker compose exec teamwatch python -m admin_portal set-password
```

The command must run with the **same DATA_DIR** as the service. In Docker this is already `/app/data`. For a custom local data directory, export `DATA_DIR` before both commands. The app does not automatically load `.env` in a plain Python invocation; Compose supplies it through `env_file`.

Security settings allow an authenticated administrator to change their password using the current password. Forgotten-password recovery uses the server-side `set-password` command above; it invalidates existing admin sessions without requiring email infrastructure. Use HTTPS and `COOKIE_SECURE=true` in production.

## What is available

- Room creation, listing, editing of name/code, blocking/unblocking and deletion.
- Persistent host and participant accounts, with name, role, room assignment, blocking and passcode changes. Passcodes are 4–16 digits and must be unique within their room. Account names are administrative labels; viewers still join with room code and passcode.
- A new room starts with one host and one participant account. The original room is imported once from `ROOM_CODE`, `HOST_PIN` and `VIEWER_PIN`. Subsequent changes are made in the portal; environment values do not overwrite stored records.
- Live room/device monitoring, reported drift, readiness, play/pause and force sync.
- Media uploads per room, including replacement uploads while current media plays. Existing playback switches when the new media becomes playable, following the viewer pipeline's existing behavior.
- Per-room deletion and all-room deletion, with literal `CONFIRM` enforced by both UI and API. Failed-upload leftovers are also cleaned. Bulk requests report per-room failures; deletion is not an atomic operation across rooms.
- Recent administrative activity, including room/account changes, password resets and media operations.

Blocking, editing credentials or deleting accounts revokes existing access. Room edits end that room's connected sessions. Account edits disconnect that room's devices; unaffected accounts can reconnect with their existing credentials. One browser cookie jar joins one viewer room at a time; use separate browser profiles for simultaneous rooms.

## Persistence and runtime

`DATA_DIR/admin.sqlite3` stores room records, salted scrypt password/passcode hashes and audit events. The existing room retains `DATA_DIR/current.json` and media folders. Additional rooms use `DATA_DIR/rooms/<immutable-room-id>/`. Deleting media never removes account records or the database. Deleting a room removes its accounts and media, but retains audit history.

The dispatcher sends viewer HTTP/WebSocket requests to isolated instances of the existing room runtime. This preserves the established playback/upload pipeline while keeping media, timelines, sockets and signing keys independent. Runtime instances are loaded with Python's module loader, released when their rooms are deleted, and shut down with the root app. The default room retains the original API paths and media layout.

Run **one Uvicorn worker**, as required by the existing in-memory playback design. Admin sessions are also held in memory and expire on restart or after 24 hours without user activity. Cookies are HTTP-only, SameSite Strict and HMAC-signed. Admin credentials are independent of host credentials. Failed admin login is limited to five attempts per client address per ten minutes. Mutating requests require a matching Origin header. Behind a reverse proxy, configure trusted proxy addresses correctly so the application sees the real client IP.

The admin WebSocket checks for changes every 250ms and reconnects after three seconds. Background updates do not renew idle sessions; user activity does. This targets the PRD's 500ms update goal, but is not a production latency/load benchmark. Device drift arrives with the viewer's existing status reports and can be absent until playback starts.

## Verification

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
node --check static/admin/app.js
node --test tests/*.test.cjs
```

Admin tests cover authentication and rate limits, idle expiry, credential revocation, room/media isolation, CRUD, persistence, password changes, audit history, live snapshots and deletion confirmation. FFmpeg/FFprobe are required for real encoding tests; otherwise those tests skip. Browser QA checked desktop and 375px mobile layouts, sign-in, editor fields and typed confirmation using a temporary data directory.

## Reliability boundaries

The router and service receive the existing runtime explicitly; they do not import `app.py`. This avoids circular imports and duplicate copies of mutable playback state. The CLI imports the entrypoint only when its password command is executed. Cold-import regression tests exercise both import orders.

This is one application, not a microservice. Ordinary admin HTTP exceptions fail that request; monitoring failures close only the admin WebSocket. A regression test injects an admin failure while viewer playback remains active. Process termination or out-of-memory failure still affects the entire application; process-level isolation would require separate services and a shared-state/IPC design.

Password operations run in worker threads, with at most two concurrent operations per application service. Account/room mutations are serialized around asynchronous validation to prevent races. SQLite uses WAL and a short lock timeout, avoiding long event-loop waits on database contention. Admin socket sends/disconnects have deadlines, idle admin sessions are pruned at login, and session/login-address counts are bounded. These safeguards reduce stalls and retained state; they do not replace a production load test or memory monitoring.

All viewer and admin assets share the main `/static` mount and HTTP cache/security middleware. The new asset URLs and legacy redirects are covered by integration tests.
