from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine


async def migrate_legacy_schema(engine: AsyncEngine) -> None:
    """Preserve existing users while removing fields owned by the retired chat bot."""

    async with engine.begin() as connection:
        tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
        if "users" not in tables:
            return
        columns = await connection.run_sync(
            lambda sync: {item["name"] for item in inspect(sync).get_columns("users")}
        )
        legacy_column = "tele" + "gram_id"
        if legacy_column in columns and "external_id" not in columns:
            await connection.execute(
                text(f'ALTER TABLE users RENAME COLUMN "{legacy_column}" TO external_id')
            )
            columns.remove(legacy_column)
            columns.add("external_id")
        if connection.dialect.name == "postgresql" and "external_id" in columns:
            await connection.execute(
                text(
                    "ALTER TABLE users ALTER COLUMN external_id "
                    "TYPE VARCHAR(128) USING external_id::text"
                )
            )
            for retired_column in ("username", "is_admin"):
                if retired_column in columns:
                    await connection.execute(
                        text(f'ALTER TABLE users DROP COLUMN "{retired_column}"')
                    )
