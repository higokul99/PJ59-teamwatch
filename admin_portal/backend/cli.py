"""Interactive server-side admin password setup and recovery."""
from .service import ADMIN_USER, digest, password_valid


def main():
    import getpass
    import sys
    if sys.argv[1:] != ['set-password']:
        raise SystemExit('Usage: python -m admin_portal set-password')
    password = getpass.getpass('New admin password: ')
    if not password_valid(password):
        raise SystemExit('Use 8–16 characters with uppercase, lowercase, number and special character.')
    if password != getpass.getpass('Confirm password: '):
        raise SystemExit('Passwords do not match.')
    import app
    with app.admin_manager.db() as db:
        db.execute("INSERT OR REPLACE INTO settings VALUES('password',?)", (digest(password),))
        app.admin_manager.audit(db, 'password.reset', ADMIN_USER)
    print('Admin password saved. Sign in at /admin as ' + ADMIN_USER)
