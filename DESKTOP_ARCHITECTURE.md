# Desktop architecture

`pywebview -> random 127.0.0.1 uvicorn/FastAPI -> aiosqlite/SQLite -> local content-addressed images`.

The launcher takes a per-user file lock, creates platformdirs paths and a persistent random signing secret, binds a random loopback port, and passes a one-use random bootstrap token. The endpoint exchanges it for an HttpOnly SameSite session and invalidates it. Existing CSRF tokens remain enabled. CSP permits self/data images only in desktop mode. `/local-media/{sha256}` serves only registered assets after safe-path resolution. Rotating logs contain operational events, never tokens or uploaded content.

Schema migrations are ordered, versioned, transactional and never recreate the database. Foreign keys are enabled on every connection. Expired order cleanup is an application responsibility rather than SQLite TTL.
