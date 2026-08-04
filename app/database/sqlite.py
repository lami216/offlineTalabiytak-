import logging
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)
LATEST_SCHEMA = 2
MIGRATIONS = {
    1: """
CREATE TABLE imports (id TEXT PRIMARY KEY, filename TEXT NOT NULL, status TEXT NOT NULL, counters TEXT NOT NULL, errors TEXT NOT NULL, processing_state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX imports_created ON imports(created_at DESC);
CREATE TABLE imported_images (id TEXT PRIMARY KEY, import_id TEXT NOT NULL REFERENCES imports(id) ON DELETE CASCADE, sequence_number INTEGER NOT NULL, original_media_name TEXT NOT NULL, hash TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, duplicate_of TEXT, linked_product_id TEXT, dimensions TEXT NOT NULL, mime_type TEXT NOT NULL DEFAULT '', image_asset TEXT, error_message TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(import_id, sequence_number));
CREATE INDEX images_hash ON imported_images(hash); CREATE INDEX images_status ON imported_images(status);
CREATE INDEX images_asset_file_id ON imported_images(json_extract(image_asset,'$.file_id'));
CREATE TABLE products (id TEXT PRIMARY KEY, name TEXT NOT NULL, normalized_name TEXT NOT NULL, primary_image TEXT NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX products_name ON products(normalized_name);
CREATE INDEX products_image_hash ON products(json_extract(primary_image,'$.hash'));
CREATE INDEX products_asset_file_id ON products(json_extract(primary_image,'$.file_id'));
CREATE TABLE orders (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE INDEX orders_expires ON orders(expires_at); CREATE INDEX orders_created ON orders(created_at DESC);
CREATE TABLE order_items (order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE, product_id TEXT NOT NULL REFERENCES products(id), product_name TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0), position INTEGER NOT NULL, PRIMARY KEY(order_id, position));
CREATE TABLE orphan_cleanup (file_id TEXT PRIMARY KEY, reason TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
""",
    2: """
CREATE INDEX IF NOT EXISTS images_asset_file_id ON imported_images(json_extract(image_asset,'$.file_id'));
CREATE INDEX IF NOT EXISTS products_image_hash ON products(json_extract(primary_image,'$.hash'));
CREATE INDEX IF NOT EXISTS products_asset_file_id ON products(json_extract(primary_image,'$.file_id'));
""",
}


class SQLiteDatabase:
    def __init__(self, path: Path):
        self.path, self.connection = Path(path), None
        self._transaction_depth = 0

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
            await self.connection.execute("BEGIN IMMEDIATE")
            try:
                await self.connection.executescript(MIGRATIONS[target])
                await self.connection.execute("DELETE FROM schema_version")
                await self.connection.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (target,)
                )
                await self.connection.commit()
            except Exception:
                await self.connection.rollback()
                raise

    async def ping(self) -> bool:
        row = await (await self.connection.execute("SELECT 1")).fetchone()
        return bool(row and row[0] == 1)

    @asynccontextmanager
    async def transaction(self):
        if self._transaction_depth:
            self._transaction_depth += 1
            try:
                yield
            finally:
                self._transaction_depth -= 1
            return
        await self.connection.execute("BEGIN IMMEDIATE")
        self._transaction_depth = 1
        try:
            yield
            await self.connection.commit()
        except Exception:
            await self.connection.rollback()
            raise
        finally:
            self._transaction_depth = 0

    async def commit(self):
        if not self._transaction_depth:
            await self.connection.commit()

    async def close(self):
        if self.connection:
            await self.connection.close()
            self.connection = None
