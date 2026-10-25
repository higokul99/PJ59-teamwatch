#!/usr/bin/env bash
# Run on your laptop. SSH/Certbot prompts remain interactive.
set -Eeuo pipefail
cd "$(dirname "$0")"
ACTION=${1:-}
case "$ACTION" in test|prod|rollback) ;; *) echo 'Usage: ./deploy.sh test|prod|rollback'; exit 2;; esac
VPS=root@200.234.39.67
if [[ -n $(git status --porcelain) ]]; then
    echo 'Commit and push your changes before deployment (working tree must be clean).'; exit 1
fi
SHA=$(git rev-parse HEAD)
if [[ "$ACTION" != rollback ]]; then
    git fetch origin main
    git merge-base --is-ancestor "$SHA" origin/main || { echo 'Push this commit to origin/main first.'; exit 1; }
fi
if [[ "$ACTION" == prod ]]; then
    read -r -p "Have you tested $SHA at https://test-teamwatch.metora.in? Type DEPLOY: " answer
    [[ "$answer" == DEPLOY ]] || exit 1
elif [[ "$ACTION" == rollback ]]; then
    read -r -p 'Roll production back to its previous release? Type ROLLBACK: ' answer
    [[ "$answer" == ROLLBACK ]] || exit 1
fi
# Multiplex this one run so the SSH password is normally requested only once.
SOCKET_DIR=$(mktemp -d /tmp/teamwatch-ssh.XXXXXX)
SOCKET=$SOCKET_DIR/socket
REMOTE_DIR=''
cleanup() {
    if [[ -n "$REMOTE_DIR" ]]; then
        ssh -S "$SOCKET" "$VPS" "rm -f '$REMOTE_DIR/remote.sh'; rmdir '$REMOTE_DIR'" </dev/null >/dev/null 2>&1 || true
    fi
    ssh -S "$SOCKET" -O exit "$VPS" >/dev/null 2>&1 || true
    rm -rf "$SOCKET_DIR"
}
trap cleanup EXIT
ssh -M -S "$SOCKET" -o ControlPersist=600 -fN "$VPS"
REMOTE_DIR=$(ssh -S "$SOCKET" "$VPS" 'mktemp -d /tmp/teamwatch-deploy.XXXXXXXX')
[[ "$REMOTE_DIR" =~ ^/tmp/teamwatch-deploy\.[A-Za-z0-9]+$ ]] || { echo 'Unexpected remote temporary directory.'; exit 1; }
scp -o "ControlPath=$SOCKET" deploy/remote.sh "$VPS:$REMOTE_DIR/remote.sh"
ssh -t -S "$SOCKET" "$VPS" "bash '$REMOTE_DIR/remote.sh' '$ACTION' '$SHA'"
