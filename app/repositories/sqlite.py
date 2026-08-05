import json
from datetime import UTC, datetime

from app.models import ImageAsset, Import, ImportedImage, Order, OrderItem, Product, now
from app.services.errors import ValidationError
from app.utils.objectid import new_id, to_object_id


def dt(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def asset(value):
    return ImageAsset(**json.loads(value)) if value else None


def dump_asset(value):
    return json.dumps(value.__dict__) if value else None


def image(row):
    return ImportedImage(
        row["id"],
        row["import_id"],
        row["sequence_number"],
        row["original_media_name"],
        row["hash"],
        row["status"],
        json.loads(row["duplicate_of"]) if row["duplicate_of"] else None,
        row["linked_product_id"],
        json.loads(row["dimensions"]),
        row["mime_type"],
        asset(row["image_asset"]),
        row["error_message"],
        dt(row["created_at"]),
        dt(row["updated_at"]),
    )


def product(row):
    return Product(
        row["id"],
        row["name"],
        row["normalized_name"],
        asset(row["primary_image"]),
        json.loads(row["metadata"]),
        dt(row["created_at"]),
        dt(row["updated_at"]),
    )


class Base:
    def __init__(self, db):
        self.db, self.c = db, db.connection

    async def one(self, sql, args=()):
        return await (await self.c.execute(sql, args)).fetchone()

    async def all(self, sql, args=()):
        return await (await self.c.execute(sql, args)).fetchall()


class SQLiteImportsRepository(Base):
    async def create(self, filename):
        x = Import(new_id(), filename)
        await self.c.execute(
            "INSERT INTO imports (id, filename, status, counters, errors, processing_state, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                x.id,
                x.filename,
                x.status,
                json.dumps(x.counters),
                json.dumps([]),
                json.dumps({}),
                x.created_at.isoformat(),
                x.updated_at.isoformat(),
            ),
        )
        await self.db.commit()
        return x

    async def get(self, id):
        r = await self.one("SELECT * FROM imports WHERE id=?", (str(to_object_id(id)),))
        return (
            Import(
                r["id"],
                r["filename"],
                r["status"],
                json.loads(r["counters"]),
                json.loads(r["errors"]),
                json.loads(r["processing_state"]),
                dt(r["created_at"]),
                dt(r["updated_at"]),
            )
            if r
            else None
        )

    async def update(self, id, **values):
        current = await self.get(id)
        if current is None:
            return None
        for k, v in values.items():
            if v is not None:
                setattr(current, k, v)
        current.updated_at = now()
        await self.c.execute(
            "UPDATE imports SET status=?,counters=?,errors=?,processing_state=?,updated_at=? WHERE id=?",
            (
                current.status,
                json.dumps(current.counters),
                json.dumps(current.errors),
                json.dumps(current.processing_state),
                current.updated_at.isoformat(),
                current.id,
            ),
        )
        await self.db.commit()
        return current

    async def update_status(self, id, status, **kwargs):
        return await self.update(id, status=status, **kwargs)

    async def list(self, limit=100):
        return [
            await self.get(r["id"])
            for r in await self.all(
                "SELECT id FROM imports ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        ]

    async def count(self):
        return (await self.one("SELECT count(*) n FROM imports"))["n"]


class SQLiteImagesRepository(Base):
    async def create(self, x):
        x.id = x.id or new_id()
        await self.c.execute(
            "INSERT INTO imported_images (id, import_id, sequence_number, original_media_name, hash, status, duplicate_of, linked_product_id, dimensions, mime_type, image_asset, error_message, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                x.id,
                x.import_id,
                x.sequence_number,
                x.original_media_name,
                x.hash,
                x.status,
                json.dumps(x.duplicate_of) if x.duplicate_of else None,
                x.linked_product_id,
                json.dumps(x.dimensions),
                x.mime_type,
                dump_asset(x.image_asset),
                x.error_message,
                x.created_at.isoformat(),
                x.updated_at.isoformat(),
            ),
        )
        await self.db.commit()
        return x

    async def get(self, id):
        r = await self.one("SELECT * FROM imported_images WHERE id=?", (str(to_object_id(id)),))
        return image(r) if r else None

    async def update(self, x):
        x.updated_at = now()
        await self.c.execute(
            "UPDATE imported_images SET hash=?,status=?,duplicate_of=?,linked_product_id=?,dimensions=?,mime_type=?,image_asset=?,error_message=?,updated_at=? WHERE id=?",
            (
                x.hash,
                x.status,
                json.dumps(x.duplicate_of) if x.duplicate_of else None,
                x.linked_product_id,
                json.dumps(x.dimensions),
                x.mime_type,
                dump_asset(x.image_asset),
                x.error_message,
                x.updated_at.isoformat(),
                x.id,
            ),
        )
        await self.db.commit()
        return x

    async def update_status(self, id, status):
        x = await self.get(id)
        if x is None:
            return None
        x.status = status
        return await self.update(x)

    async def link_product(self, id, pid):
        x = await self.get(id)
        if x is None:
            return None
        x.linked_product_id = pid
        x.status = "saved_as_product"
        return await self.update(x)

    async def find_duplicate_by_hash(self, h, exclude_id=None):
        r = await self.one(
            "SELECT * FROM imported_images WHERE hash=? AND image_asset IS NOT NULL AND status NOT IN ('deleted','ignored') AND id!=? ORDER BY created_at LIMIT 1",
            (h, exclude_id or ""),
        )
        return image(r) if r else None

    async def list_images(self, i, status="all", page=1, size=48):
        hidden = ("deleted", "ignored")
        if status == "all":
            where = "import_id=? AND status NOT IN (?,?)"
            args = [i, *hidden, (max(page, 1) - 1) * size, size]
        else:
            where = "import_id=? AND status=?"
            args = [i, status, (max(page, 1) - 1) * size, size]
        return [
            image(r)
            for r in await self.all(
                f"SELECT * FROM imported_images WHERE {where} ORDER BY sequence_number LIMIT ?,?",
                args,
            )
        ]

    async def status_counts(self, i):
        return {
            r["status"]: r["n"]
            for r in await self.all(
                "SELECT status,count(*) n FROM imported_images WHERE import_id=? AND status NOT IN ('deleted','ignored') GROUP BY status",
                (i,),
            )
        }

    async def mark_deleted(self, id):
        x = await self.get(id)
        if x is None:
            return None
        x.status = "deleted"
        x.image_asset = None
        x.linked_product_id = None
        return await self.update(x)

    async def count(self, status=None):
        return (
            await self.one(
                "SELECT count(*) n FROM imported_images" + (" WHERE status=?" if status else ""),
                (status,) if status else (),
            )
        )["n"]

    async def asset_references(self, f, exclude_id=None):
        return (
            await self.one(
                "SELECT count(*) n FROM imported_images WHERE json_extract(image_asset,'$.file_id')=? AND status NOT IN ('deleted','ignored') AND id!=?",
                (f, exclude_id or ""),
            )
        )["n"]

    async def abandoned(self, cutoff):
        return [
            image(r)
            for r in await self.all(
                "SELECT * FROM imported_images WHERE created_at<? AND status IN ('unnamed','ignored')",
                (cutoff.isoformat(),),
            )
        ]

    async def find_asset_by_file_id(self, file_id):
        r = await self.one(
            "SELECT image_asset FROM imported_images WHERE json_extract(image_asset,'$.file_id')=? AND image_asset IS NOT NULL AND status NOT IN ('deleted','ignored') LIMIT 1",
            (file_id,),
        )
        return asset(r["image_asset"]) if r else None


class SQLiteProductsRepository(Base):
    async def create(self, x):
        await self.c.execute(
            "INSERT INTO products (id, name, normalized_name, primary_image, metadata, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (
                x.id,
                x.name,
                x.normalized_name,
                dump_asset(x.primary_image),
                json.dumps(x.metadata),
                x.created_at.isoformat(),
                x.updated_at.isoformat(),
            ),
        )
        await self.db.commit()
        return x

    async def get(self, id):
        r = await self.one("SELECT * FROM products WHERE id=?", (str(to_object_id(id)),))
        return product(r) if r else None

    async def find_by_hash(self, h):
        r = await self.one(
            "SELECT * FROM products WHERE json_extract(primary_image,'$.hash')=?", (h,)
        )
        return product(r) if r else None

    async def search(self, q, page=1, size=24):
        pattern = f"%{q}%"
        total = (
            await self.one(
                "SELECT count(*) n FROM products WHERE normalized_name LIKE ?", (pattern,)
            )
        )["n"]
        rows = await self.all(
            "SELECT * FROM products WHERE normalized_name LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (pattern, size, (max(page, 1) - 1) * size),
        )
        return [product(r) for r in rows], total

    async def update(self, x):
        x.updated_at = now()
        await self.c.execute(
            "UPDATE products SET name=?,normalized_name=?,primary_image=?,metadata=?,updated_at=? WHERE id=?",
            (
                x.name,
                x.normalized_name,
                dump_asset(x.primary_image),
                json.dumps(x.metadata),
                x.updated_at.isoformat(),
                x.id,
            ),
        )
        await self.db.commit()
        return x

    async def delete(self, id):
        r = await self.c.execute("DELETE FROM products WHERE id=?", (str(to_object_id(id)),))
        await self.db.commit()
        return r

    async def count(self):
        return (await self.one("SELECT count(*) n FROM products"))["n"]

    async def asset_references(self, f, exclude_id=None):
        return (
            await self.one(
                "SELECT count(*) n FROM products WHERE json_extract(primary_image,'$.file_id')=? AND id!=?",
                (f, exclude_id or ""),
            )
        )["n"]

    async def recent(self, limit=6):
        return [
            product(r)
            for r in await self.all(
                "SELECT * FROM products ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        ]

    async def find_asset_by_file_id(self, file_id):
        r = await self.one(
            "SELECT primary_image FROM products WHERE json_extract(primary_image,'$.file_id')=? LIMIT 1",
            (file_id,),
        )
        return asset(r["primary_image"]) if r else None


class SQLiteOrdersRepository(Base):
    async def _make(self, r):
        items = [
            OrderItem(x["product_id"], x["product_name"], x["quantity"], x["position"])
            for x in await self.all(
                "SELECT * FROM order_items WHERE order_id=? ORDER BY position", (r["id"],)
            )
        ]
        return Order(
            r["id"],
            r["title"],
            items,
            dt(r["created_at"]),
            dt(r["updated_at"]),
            dt(r["expires_at"]),
        )

    async def create(self, o):
        await self.c.execute("BEGIN IMMEDIATE")
        try:
            await self.c.execute(
                "INSERT INTO orders (id, title, created_at, updated_at, expires_at) VALUES (?,?,?,?,?)",
                (
                    o.id,
                    o.title,
                    o.created_at.isoformat(),
                    o.updated_at.isoformat(),
                    o.expires_at.isoformat(),
                ),
            )
            await self.c.executemany(
                "INSERT INTO order_items (order_id, product_id, product_name, quantity, position) VALUES (?,?,?,?,?)",
                [(o.id, i.product_id, i.product_name, i.quantity, i.position) for i in o.items],
            )
            await self.c.commit()
        except Exception:
            await self.c.rollback()
            raise
        return o

    async def get(self, id):
        r = await self.one("SELECT * FROM orders WHERE id=?", (str(to_object_id(id)),))
        return await self._make(r) if r else None

    async def get_active(self, id):
        r = await self.one(
            "SELECT * FROM orders WHERE id=? AND expires_at>?",
            (str(to_object_id(id)), datetime.now(UTC).isoformat()),
        )
        return await self._make(r) if r else None

    async def list_active(self, page=1, size=24):
        return [
            await self._make(r)
            for r in await self.all(
                "SELECT * FROM orders WHERE expires_at>? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (datetime.now(UTC).isoformat(), size, (max(page, 1) - 1) * size),
            )
        ]

    async def update(self, o):
        async with self.db.transaction():
            await self.delete_items(o.id)
            result = await self.c.execute(
                "UPDATE orders SET title=?,updated_at=? WHERE id=?",
                (o.title, o.updated_at.isoformat(), o.id),
            )
            if result.rowcount == 0:
                raise ValidationError("الطلبية غير موجودة")
            await self.c.executemany(
                "INSERT INTO order_items (order_id, product_id, product_name, quantity, position) VALUES (?,?,?,?,?)",
                [(o.id, i.product_id, i.product_name, i.quantity, i.position) for i in o.items],
            )
        return o

    async def delete_items(self, id):
        await self.c.execute("DELETE FROM order_items WHERE order_id=?", (id,))

    async def delete(self, id):
        r = await self.c.execute(
            "DELETE FROM orders WHERE id=? AND expires_at>?", (id, datetime.now(UTC).isoformat())
        )
        await self.db.commit()
        return r

    async def cleanup_expired(self):
        r = await self.c.execute(
            "DELETE FROM orders WHERE expires_at<=?", (datetime.now(UTC).isoformat(),)
        )
        await self.db.commit()
        return r.rowcount

    async def count_active(self):
        return (
            await self.one(
                "SELECT count(*) n FROM orders WHERE expires_at>?", (datetime.now(UTC).isoformat(),)
            )
        )["n"]

    async def active_product_references(self, p):
        return (
            await self.one(
                "SELECT count(*) n FROM order_items i JOIN orders o ON o.id=i.order_id WHERE i.product_id=? AND o.expires_at>?",
                (p, datetime.now(UTC).isoformat()),
            )
        )["n"]

    async def recent(self, limit=6):
        return await self.list_active(1, limit)


class SQLiteOrphansRepository(Base):
    async def record(self, f, reason):
        await self.c.execute(
            "INSERT INTO orphan_cleanup (file_id, reason, status, created_at, updated_at) VALUES (?,?,'pending',?,?) ON CONFLICT(file_id) DO UPDATE SET reason=excluded.reason,updated_at=excluded.updated_at",
            (f, str(reason)[:1000], now().isoformat(), now().isoformat()),
        )
        await self.db.commit()
