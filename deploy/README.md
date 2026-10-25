# TeamWatch on the Metora VPS

## Deploy from your laptop

The repository includes `deploy.sh` configured for `root@200.234.39.67`:

```sh
./deploy.sh test
./deploy.sh prod
./deploy.sh rollback
```

Commit and push your local changes to `origin/main` first. Test uses
`test-teamwatch.metora.in` on loopback port 8890; production uses
`teamwatch.metora.in` on loopback port 8891. The script refuses conflicting
initial ports, dirty checkouts, unpushed commits, and production commits that
have not completed the test deployment. SSH passwords and key passphrases are
entered in your terminal. An SSH control socket is removed when the command
finishes; passwords are never saved by the script.

The test command runs the Docker test suite and builds a release image on the
VPS. Production reuses that tested image. The first deployment creates a private
`.env`, a dedicated Nginx site, and requests a certificate through the existing
Certbot installation. Follow any Certbot prompts yourself. Application health
is verified over HTTPS. Before production, verify the actual test site in your
browser, then type `DEPLOY` at the laptop prompt. This is your approval step.

Rollback asks for `ROLLBACK`, switches to the recorded previous production
commit and its existing image, and preserves the named media volume. Failed
application or HTTPS health checks attempt to restore the prior running release.
Do not prune release images you may need for rollback. Release records live in
`/srv/apps/teamwatch/{test,prod}/.deploy`, outside Git. A first deployment has no
previous release to restore and stops its service if activation fails.

The script configures Nginx only on first setup and checks the existing site on
later releases. Changes to domain, port, `.env`, Nginx settings, and media contents
are not rolled back with application code. Do not run deployments during uploads
or conversion. Playback restarts paused after a container restart.


Use dedicated directories and domains; do not reuse Metohub's site configuration:

- `/srv/apps/teamwatch/test/teamwatch-code`
- `/srv/apps/teamwatch/prod/teamwatch-code`

Each directory is an independent clone of the same Git repository. Deploy an exact tested commit in both. `COMPOSE_PROJECT_NAME=teamwatch-test` and `teamwatch-prod` isolate Docker volumes and networks despite identical directory basenames. Keep those names stable across releases. TeamWatch has no database; its persistent data is the uploaded/prepared media volume.

## Before installation

Verify existing Nginx sites, port assignments (`ss -ltnp`), DNS, disk, RAM, and Docker Compose. Choose two unused loopback ports and two dedicated domains. Do not modify existing Metohub services. Commit and push this project before cloning it to the VPS.

In each clone, create a fresh configuration, substituting the verified unused port:

```sh
python3 deploy/init_env.py test --port 8890
# For the production clone instead:
# python3 deploy/init_env.py prod --port 8891
```

The commands refuse to overwrite existing `.env` files. They generate independent session secrets and set HTTPS cookies. Ports above are proposals only. Review PINs locally in `.env`, without pasting secrets into logs. Do not copy test secrets to production.

## Validate and start testing

Run in the test clone:

```sh
docker build --target test -t teamwatch-tests .
docker run --rm teamwatch-tests
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 120
docker compose ps
docker compose logs --tail=100
curl --fail http://127.0.0.1:8890/health
```

Substitute the selected port in curl. Keep the app bound to localhost. Do not open its port in the firewall. Leave one worker and one replica.

## Nginx and HTTPS

1. Render `nginx.conf.template` using the actual domain and loopback port. Install as a new, uniquely named file in `/etc/nginx/sites-available/`, then link that file in `sites-enabled`. Never overwrite a pre-existing site. DNS A records must point to the VPS; only publish an AAAA record if IPv6 works.
2. Run `nginx -t` before reloading Nginx. If validation fails, remove only the new symlink and fix this site's configuration.
3. Use the VPS's existing certificate-management procedure. If Certbot's Nginx integration is already installed, run `certbot --nginx -d YOUR_DOMAIN --redirect`. Confirm the certificate and HTTPS response before using the login form. The configuration initially serves HTTP only for bootstrapping.
4. Verify the actual Docker bridge gateway/source address for proxy requests and set `FORWARDED_ALLOW_IPS` to that address in `.env`; recreate the app container. Never set it to `*`. Until configured, login throttling may group proxied users under one IP. Nginx overwrites forwarded IP headers in this template; preserve that behavior. These settings assume Nginx runs on the host, not behind another proxy/CDN.
5. Keep the Nginx upload limit aligned with `MAX_UPLOAD_MB`. Request buffering is disabled to stream uploads directly to the app. Byte-range streaming and WebSocket upgrade headers are preserved.

References: [Nginx WebSockets](https://nginx.org/en/docs/http/websocket.html), [proxy buffering](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_request_buffering).

## Production release

Verify host login, viewer login, sample upload/conversion, all three modes, play/pause/seeking, and a late join over the test HTTPS domain. Record the tested Git SHA. Then deploy that exact commit in the production clone, using its independent `.env`, port, Nginx site, and volume. Check HTTPS, logs, health, and real phone playback again. Keep the prior commit SHA for rollback.

For updates: verify a clean Git worktree, fetch, check out the tested release, then `docker compose up -d --build --wait`. Schedule the restart: active viewers will disconnect and playback restarts paused. Do not update during conversion.

## Media backup and rollback

Before a risky change, finish any conversion and stop the app during a maintenance window. Copy `/app/data` from the stopped service to a new protected backup directory outside the repository using `docker compose cp teamwatch:/app/data /srv/backups/teamwatch/UNIQUE_BACKUP_NAME`. Create that parent directory with restrictive permissions first. Restart with `docker compose start`, verify backup contents, and retain an encrypted/off-site copy plus a separately protected `.env` backup. Test restoration in an isolated environment before relying on it.

For a code rollback, check out the prior recorded commit and rebuild with the same Compose project name and `.env`. The named media volume is retained. Restore media only if needed, into the correct environment, while the application is stopped; container user 10001 must retain read/write access. Never use `docker compose down -v`, volume pruning, or manual edits under `/var/lib/docker` as a release step.

The first version retains one active movie, deleting the previous prepared movie after successful replacement. Back up anything you need to retain before replacing it. Allow several times the movie's size in free space for transcoding and backup.
