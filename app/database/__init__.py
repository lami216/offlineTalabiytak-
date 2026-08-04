def __getattr__(name):
    if name == "SQLiteDatabase":
        from app.database.sqlite import SQLiteDatabase

        return SQLiteDatabase
    if name in {"close_mongo", "create_mongo", "ensure_indexes", "verify_database"}:
        from app.database import mongo

        return getattr(mongo, name)
    raise AttributeError(name)


__all__ = ["SQLiteDatabase", "close_mongo", "create_mongo", "ensure_indexes", "verify_database"]
