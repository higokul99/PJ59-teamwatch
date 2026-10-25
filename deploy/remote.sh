#!/usr/bin/env bash
# Invoked by deploy.sh on the VPS. State is kept outside the Git checkout.
set -Eeuo pipefail
ACTION=${1:-}
SHA=${2:-}
case "$ACTION" in test) ENVIRONMENT=test; PORT=8890; DOMAIN=test-teamwatch.metora.in;; prod|rollback) ENVIRONMENT=prod; PORT=8891; DOMAIN=teamwatch.metora.in;; *) exit 2;; esac
[[ "$SHA" =~ ^[a-f0-9]{40}$ ]] || exit 2
[[ $EUID == 0 ]] || { echo 'Run through the root SSH connection.'; exit 1; }
for command in docker git python3 nginx certbot curl flock; do command -v "$command" >/dev/null || { echo "Missing: $command"; exit 1; }; done
BASE=/srv/apps/teamwatch/$ENVIRONMENT
CODE=$BASE/teamwatch-code
STATE=$BASE/.deploy
SITE=/etc/nginx/sites-available/teamwatch-$ENVIRONMENT
LINK=/etc/nginx/sites-enabled/teamwatch-$ENVIRONMENT
mkdir -p "$STATE"
chmod 700 "$STATE"
exec 9>"$STATE/lock"
flock -n 9 || { echo 'Another deployment is running for this environment.'; exit 1; }
python3 - "$DOMAIN" <<'PY'
import socket, sys
addresses = {entry[4][0] for entry in socket.getaddrinfo(sys.argv[1], 443, socket.AF_INET)}
if addresses != {'200.234.39.67'}:
    raise SystemExit(f'DNS must point only to 200.234.39.67; found {addresses}')
PY
if [[ ! -d "$CODE" ]]; then
    git clone https://github.com/higokul99/PJ59-teamwatch.git "$CODE"
fi
cd "$CODE"
[[ $(git remote get-url origin) == https://github.com/higokul99/PJ59-teamwatch.git ]] || { echo 'Unexpected repository; stopping.'; exit 1; }
[[ -z $(git status --porcelain) ]] || { echo 'VPS checkout has local changes; stopping.'; exit 1; }
OLD=''
[[ ! -f "$STATE/current" ]] || OLD=$(cat "$STATE/current")
if [[ "$ACTION" == rollback ]]; then
    [[ -s "$STATE/previous" ]] || { echo 'No previous production release is recorded.'; exit 1; }
    SHA=$(cat "$STATE/previous")
    [[ "$SHA" =~ ^[a-f0-9]{40}$ ]] || exit 1
    docker image inspect "teamwatch-release:$SHA" >/dev/null || { echo 'Previous Docker image is missing.'; exit 1; }
    echo "Rolling back $OLD to $SHA"
else
    git fetch origin main
    git merge-base --is-ancestor "$SHA" origin/main || { echo 'Commit is not on origin/main.'; exit 1; }
    if [[ "$ACTION" == prod ]]; then
        [[ -s /srv/apps/teamwatch/test/.deploy/tested ]] && [[ $(cat /srv/apps/teamwatch/test/.deploy/tested) == "$SHA" ]] || { echo 'Deploy this exact commit to test first.'; exit 1; }
        docker image inspect "teamwatch-release:$SHA" >/dev/null || { echo 'Tested image is missing; run test deployment again.'; exit 1; }
    fi
fi
git checkout --detach "$SHA"
if [[ ! -f .env ]]; then
    python3 - "$PORT" <<'PY'
import socket, sys
with socket.socket() as probe:
    try: probe.bind(('127.0.0.1', int(sys.argv[1])))
    except OSError: raise SystemExit('Proposed port is already occupied; stop and choose another.')
PY
    python3 deploy/init_env.py "$ENVIRONMENT" --port "$PORT"
fi
chmod 600 .env
# Verify stable project/port/volume identity without printing secrets.
python3 - "$ENVIRONMENT" "$PORT" <<'PY'
from pathlib import Path
import sys
values = dict(line.split('=',1) for line in Path('.env').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
expected = {'COMPOSE_PROJECT_NAME':'teamwatch-'+sys.argv[1], 'PORT':sys.argv[2], 'BIND_ADDRESS':'127.0.0.1', 'COOKIE_SECURE':'true'}
for key, value in expected.items():
    if values.get(key) != value: raise SystemExit(f'Unexpected {key} in .env; inspect locally.')
if len(values.get('SESSION_SECRET','')) < 32: raise SystemExit('Set a strong SESSION_SECRET first.')
PY
if [[ "$ACTION" == test ]]; then
    docker build --target test -t "teamwatch-tests:$SHA" .
    docker run --rm "teamwatch-tests:$SHA"
    docker build --target production -t "teamwatch-release:$SHA" .
fi
write_override() {
    printf 'services:\n  teamwatch:\n    image: teamwatch-release:%s\n    pull_policy: never\n' "$1" > "$STATE/image.yaml"
}
dc() { docker compose --project-name "teamwatch-$ENVIRONMENT" -f "$CODE/compose.yaml" -f "$STATE/image.yaml" "$@"; }
NEW_SITE=0
recover() {
    result=$?
    trap - ERR
    echo 'Deployment failed. Attempting to restore the prior application release.'
    if [[ -n "$OLD" ]]; then
        git checkout --detach "$OLD" && write_override "$OLD" && dc up -d --no-build --pull never --wait --wait-timeout 120 || echo 'Automatic restoration failed; inspect docker compose logs.'
    else
        dc stop teamwatch || true
    fi
    if [[ "$NEW_SITE" == 1 ]]; then
        rm -f "$LINK"
        nginx -t && systemctl reload nginx || true
    fi
    exit "$result"
}
trap recover ERR
write_override "$SHA"
dc config --quiet
dc up -d --no-build --pull never --wait --wait-timeout 120
curl --fail --silent --show-error "http://127.0.0.1:$PORT/health" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["ok"] and d["ffmpeg"]'
if [[ ! -e "$SITE" ]]; then
    [[ ! -e "$LINK" && ! -L "$LINK" ]] || { echo 'Nginx site link already exists; inspect it.'; false; }
    python3 - "$DOMAIN" "$PORT" "$SITE" <<'PY'
from pathlib import Path
import sys
content = Path('deploy/nginx.conf.template').read_text().replace('__DOMAIN__', sys.argv[1]).replace('__PORT__', sys.argv[2])
with open(sys.argv[3], 'x') as target:
    target.write('# Managed by TeamWatch deployment\n' + content)
PY
fi
# Never adopt a site belonging to another project.
rg_marker='# Managed by TeamWatch deployment'
grep -qF "$rg_marker" "$SITE"
if [[ -L "$LINK" ]]; then
    [[ $(readlink "$LINK") == "$SITE" ]] || { echo 'Unexpected Nginx link.'; false; }
else
    [[ ! -e "$LINK" ]] || { echo 'Unexpected Nginx file.'; false; }
    ln -s "$SITE" "$LINK"
    NEW_SITE=1
fi
nginx -t
systemctl reload nginx
# First run asks for certificate account details/terms in this terminal.
if ! curl --fail --silent --show-error --max-time 15 "https://$DOMAIN/health" >/dev/null 2>&1; then
    certbot --nginx -d "$DOMAIN" --redirect
fi
curl --fail --silent --show-error --max-time 20 "https://$DOMAIN/health" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["ok"] and d["ffmpeg"]'
# Record only completed releases; keep the prior image available locally.
if [[ -n "$OLD" && "$OLD" != "$SHA" ]]; then printf '%s\n' "$OLD" > "$STATE/previous"; fi
printf '%s\n' "$SHA" > "$STATE/current"
if [[ "$ENVIRONMENT" == test ]]; then printf '%s\n' "$SHA" > "$STATE/tested"; fi
trap - ERR
dc ps
echo "Ready: https://$DOMAIN (release $SHA)"
echo 'Verify upload, all playback modes, synchronization, and a late join in a real browser.'
