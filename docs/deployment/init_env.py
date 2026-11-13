"""Create a separate VPS environment without overwriting existing secrets."""
import argparse
import os
from pathlib import Path
import secrets

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('environment', choices=['test', 'prod'])
parser.add_argument('--port', type=int, required=True)
args = parser.parse_args()
if not 1024 <= args.port <= 65535:
    parser.error('Use an available port between 1024 and 65535.')
content = f'''COMPOSE_PROJECT_NAME=teamwatch-{args.environment}
ROOM_CODE=8889292
VIEWER_PIN=8989
HOST_PIN=9292
SESSION_SECRET={secrets.token_hex(32)}
COOKIE_SECURE=true
MAX_UPLOAD_MB=10240
BIND_ADDRESS=127.0.0.1
PORT={args.port}
# Set to the verified Docker gateway IP seen by this container for Nginx requests.
FORWARDED_ALLOW_IPS=127.0.0.1
'''
try:
    fd = os.open(Path('.env'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    parser.error('.env already exists; refusing to overwrite it.')
with os.fdopen(fd, 'w') as stream:
    stream.write(content)
print(f'Created private .env for teamwatch-{args.environment}; HTTPS is required for login.')
