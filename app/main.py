import asyncio
import logging

import uvicorn
from fastapi import FastAPI

from app.api import router as api_router
from app.bot import create_dispatcher
from app.config import get_settings
from app.db import engine
from app.models import Base

settings = get_settings()
app = FastAPI(title="BabkiBot API", version="0.1.0")
app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def run() -> None:
    logging.basicConfig(level=settings.log_level)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    bot, dispatcher = create_dispatcher(settings)
    server = uvicorn.Server(
        uvicorn.Config(app, host="0.0.0.0", port=8000, log_level=settings.log_level.lower())
    )
    try:
        await asyncio.gather(server.serve(), dispatcher.start_polling(bot))
    finally:
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
