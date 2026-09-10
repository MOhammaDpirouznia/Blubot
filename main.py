import asyncio
import logging
import uvicorn
import config
from database.connection import init_db
from core.poller import run_transaction_poller, set_poller_bot
from bot.bot_instance import create_bot_application
from api.app import app as fastapi_app

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("main")

async def main():
    logger.info("Initializing BluPal Platform...")

    # 1. Initialize SQLite / PostgreSQL database tables
    await init_db()
    logger.info("Database initialized successfully.")

    # 2. Setup Telegram Bot
    bot_app = create_bot_application()
    if bot_app:
        set_poller_bot(bot_app.bot)
        await bot_app.initialize()
        await bot_app.start()
        if bot_app.updater:
            await bot_app.updater.start_polling()
        logger.info("Telegram Bot started successfully.")
    else:
        logger.warning("Telegram Bot skipped (No BOT_TOKEN configured in .env).")

    # 3. Launch background transaction poller
    poller_task = asyncio.create_task(run_transaction_poller())

    # 4. Launch FastAPI REST server with Uvicorn
    uvicorn_config = uvicorn.Config(
        app=fastapi_app,
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        log_level="info",
        loop="asyncio"
    )
    server = uvicorn.Server(uvicorn_config)
    logger.info(f"API Server listening at http://{config.SERVER_HOST}:{config.SERVER_PORT}")

    try:
        await server.serve()
    finally:
        poller_task.cancel()
        if bot_app and bot_app.updater:
            await bot_app.updater.stop()
            await bot_app.stop()
            await bot_app.shutdown()
        logger.info("BluPal Platform shut down gracefully.")

if __name__ == "__main__":
    asyncio.run(main())
