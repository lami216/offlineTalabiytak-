# Local data

Per-user data is under `%LOCALAPPDATA%\Talabiytak\data`: `talabiytak.db`, `images`, `logs`, `temp`, and `settings.key`. It survives upgrades, reinstall and default uninstall. The optional Arabic uninstall checkbox is the only automatic deletion path.

For backup, close Talabiytak and copy the entire `%LOCALAPPDATA%\Talabiytak` directory. Restore it only while the application is closed. Logs for support are in `data\logs`; do not send the database or images unless explicitly required.
