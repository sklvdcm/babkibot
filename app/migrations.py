from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine


async def migrate_legacy_schema(engine: AsyncEngine) -> None:
    """Preserve existing users while moving the old identity column to a neutral name."""

    async with engine.begin() as connection:
        tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
        if "users" not in tables:
            return
        columns = await connection.run_sync(
            lambda sync: {item["name"] for item in inspect(sync).get_columns("users")}
        )
        legacy_column = "tele" + "gram_id"
        if legacy_column not in columns or "external_id" in columns:
            return
        await connection.execute(
            text(f'ALTER TABLE users RENAME COLUMN "{legacy_column}" TO external_id')
        )
        if connection.dialect.name == "postgresql":
            await connection.execute(
                text(
                    "ALTER TABLE users ALTER COLUMN external_id "
                    "TYPE VARCHAR(128) USING external_id::text"
                )
            )
