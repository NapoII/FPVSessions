"""
WSGI entry point for Gunicorn/Uwsgi.

Gunicorn ExecStart should point to `wsgi:app` with WorkingDirectory set to
the project root that contains this file.

Example (systemd):
    ExecStart=/path/to/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8007 wsgi:app

To become the system user:
1. Use `sudo -i -u <username>` to switch to the desired user.
2. Ensure you have the necessary permissions to access the project files.
3. Verify the environment variables required for the application are set.
"""

import os
import sys

# Ensure any required environment defaults here if needed
# os.environ.setdefault('FLASK_SECRET_KEY', 'change-me')
# Optionally set FPV_BASE via env or sessions_config.json inside flask_app/

ROOT = os.path.abspath(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask_app.app import app  # noqa: E402  (Flask app instance)
application = app


if __name__ == "__main__":
    # Handy for local ad-hoc run (not for production)
    port = int(os.environ.get("PORT", 8007))
    app.run(host="0.0.0.0", port=port, debug=True)
