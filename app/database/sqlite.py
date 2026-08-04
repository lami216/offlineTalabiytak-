import logging
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)
LATEST_SCHEMA = 1
MIGRATIONS = {
    1: """
CREATE TABLE imports (id TEXT PRIMARY KEY, filename TEXT NOT NULL, status TEXT NOT NULL, counters TEXT NOT NULL, errors TEXT NOT NULL, processing_state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX imports_created ON imports(created_at DESC);
CREATE TABLE imported_images (id TEXT PRIMARY KEY, import_id TEXT NOT NULL REFERENCES imports(id) ON DELETE CASCADE, sequence_number INTEGER NOT NULL, original_media_name TEXT NOT NULL, hash TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, duplicate_of TEXT, linked_product_id TEXT, dimensions TEXT NOT NULL, mime_type TEXT NOT NULL DEFAULT '', image_asset TEXT, error_message TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(import_id, sequence_number));
CREATE INDEX images_hash ON imported_images(hash); CREATE INDEX images_status ON imported_images(status);
CREATE TABLE products (id TEXT PRIMARY KEY, name TEXT NOT NULL, normalized_name TEXT NOT NULL, primary_image TEXT NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX products_name ON products(normalized_name);
CREATE TABLE orders (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE INDEX orders_expires ON orders(expires_at); CREATE INDEX orders_created ON orders(created_at DESC);
CREATE TABLE order_items (order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE, product_id TEXT NOT NULL REFERENCES products(id), product_name TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0), position INTEGER NOT NULL, PRIMARY KEY(order_id, position));
CREATE TABLE orphan_cleanup (file_id TEXT PRIMARY KEY, reason TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
"""
}


class SQLiteDatabase:
    def __init__(self, path: Path):
        self.path, self.connection = Path(path), None

    async def open(self):
        self.connection = await aiosqlite.connect(self.path)
        self.connection.row_factory = aiosqlite.Row
        await self.connection.execute("PRAGMA foreign_keys = ON")
        await self.migrate()
        return self

    async def migrate(self):
        await self.connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
        )
        row = await (
            await self.connection.execute("SELECT version FROM schema_version LIMIT 1")
        ).fetchone()
        version = row[0] if row else 0
        for target in range(version + 1, LATEST_SCHEMA + 1):
            log.info("Applying SQLite migration %s", target)
            script = (
                "BEGIN IMMEDIATE;\n"
                + MIGRATIONS[target]
                + f"\nDELETE FROM schema_version; INSERT INTO schema_version VALUES ({target});\nCOMMIT;"
            )
            await self.connection.executescript(script)
        await self.connection.commit()

    async def close(self):
        if self.connection:
            await self.connection.close()
