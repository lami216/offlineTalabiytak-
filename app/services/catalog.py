from app.models import ImageStatus


class CatalogQueryService:
    def __init__(self, database, imports, images, products, orders=None):
        self.database, self.imports, self.images, self.products = (
            database,
            imports,
            images,
            products,
        )
        self.orders = orders

    async def readiness(self):
        ping = getattr(type(self.database), "ping", None)
        if ping is not None:
            ok = await self.database.ping()
            database_name = (
                "sqlite" if self.database.__class__.__name__ == "SQLiteDatabase" else "mongo"
            )
        else:
            await self.database.command("ping")
            ok = True
            database_name = "mongo"
        if not ok:
            raise RuntimeError("database is not ready")
        response = {"status": "ready", "database": database_name}
        response["storage"] = "local" if database_name == "sqlite" else "imagekit"
        return response

    async def dashboard(self):
        return (
            {
                "products": await self.products.count(),
                "unnamed": await self.images.count(ImageStatus.unnamed.value),
                "batches": await self.imports.count(),
                "orders": await self.orders.count_active() if self.orders else 0,
            },
            await self.imports.list(6),
            await self.products.recent(6),
            await self.orders.recent(6) if self.orders else [],
        )
