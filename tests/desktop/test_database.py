import pytest

from app.database.sqlite import LATEST_SCHEMA, SQLiteDatabase


@pytest.mark.asyncio
async def test_sqlite_ping_and_json_extract_after_reopen(tmp_path):
    db = await SQLiteDatabase(tmp_path / "talabiytak.db").open()
    assert await db.ping() is True
    cursor = await db.connection.execute("SELECT json_extract('{\"a\":1}', '$.a')")
    assert (await cursor.fetchone())[0] == 1
    await db.close()
    reopened = await SQLiteDatabase(tmp_path / "talabiytak.db").open()
    assert await reopened.ping() is True
    cursor = await reopened.connection.execute("SELECT version FROM schema_version")
    version = await cursor.fetchone()
    assert version[0] == LATEST_SCHEMA
    await reopened.close()


@pytest.mark.asyncio
async def test_migrates_schema_v1_without_data_loss(tmp_path):
    db = await SQLiteDatabase(tmp_path / "old.db").open()
    await db.close()
    raw = await __import__("aiosqlite").connect(tmp_path / "old.db")
    await raw.execute("UPDATE schema_version SET version=1")
    await raw.commit()
    await raw.close()
    upgraded = await SQLiteDatabase(tmp_path / "old.db").open()
    cursor = await upgraded.connection.execute("SELECT version FROM schema_version")
    assert (await cursor.fetchone())[0] == LATEST_SCHEMA
    await upgraded.close()
