# Desktop Completion Audit

## Critical
- SQLite repositories used implicit `INSERT INTO ... VALUES` statements, including a broken `imported_images` insert whose placeholders did not match the schema.
- `/ready` used MongoDB-only `database.command("ping")`, so SQLite desktop readiness failed.
- Desktop runtime imported BSON/ImageKit through shared utilities and storage imports.
- Order updates were not atomic and could delete existing items before a later insert failure.
- `/local-media/{asset_id}` queried SQLite directly and called a private storage method.

## High
- SQLite migrations were not expressed with explicit schema-version column writes and lacked health/transaction helpers.
- Missing-record updates could raise unclear `AttributeError`s.
- Desktop bootstrap token lacked expiry metadata and Uvicorn access logging was not disabled.
- Local port selection had a bind race.

## Medium
- Desktop dependencies were not split from web-only dependencies.
- Packaging/build scripts needed stronger smoke-test and installer verification steps.
- Local storage used ImageKit-named exceptions and types.

## Cosmetic
- Project metadata still described the app as ImageKit-backed even for desktop builds.
- Some user-facing cleanup text still mentions ImageKit for shared web/desktop templates.
