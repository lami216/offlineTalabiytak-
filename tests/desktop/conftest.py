"""Desktop test configuration isolated from web-only fixtures."""

import os

os.environ.update(
    SECRET_KEY="abcdefghijklmnopqrstuvwxyz1234567890",
    ADMIN_USERNAME="admin",
    ADMIN_PASSWORD="strong-password",
    APP_ENV="desktop",
    TRUSTED_HOSTS="testserver,localhost,127.0.0.1",
    TALABIYTAK_DESKTOP_LAUNCH="1",
)
