import asyncio
import logging
import os
import sys

# Ensure UTF-8 output encoding for emojis and non-ASCII text on all consoles/platforms
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure parent directory is in sys.path so engine and subprocess modules can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from bot.config import config
from bot.database.session import async_session, init_db
from bot.middleware.db import DbSessionMiddleware
from bot.middleware.auth import ThrottlingMiddleware
from bot.middleware.forcesub import ForceSubMiddleware
from bot.middleware.daily_bonus import DailyBonusMiddleware
from bot.middleware.seller_check import SellerCheckMiddleware
from bot.handlers import user, admin

logging.basicConfig(level=getattr(logging, config.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)

async def handle_ping(request):
    return web.Response(text="Aadhaar Bot is running healthy!")

async def start_web_server():
    """Runs a lightweight HTTP server on PORT for Render free tier keep-alive."""
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", config.port or 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Ping web server started on port {port} for Render")

async def main():
    # 1. Start web server for Render health checks
    await start_web_server()

    # 2. Initialize Telegram Bot & Dispatcher
    bot = Bot(token=config.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    # 3. Register Middlewares
    dp.update.middleware(DbSessionMiddleware(async_session))
    dp.message.middleware(ThrottlingMiddleware(limit_seconds=1.0))
    dp.message.middleware(SellerCheckMiddleware())
    dp.callback_query.middleware(SellerCheckMiddleware())
    dp.message.middleware(ForceSubMiddleware())
    dp.callback_query.middleware(ForceSubMiddleware())
    dp.message.middleware(DailyBonusMiddleware())

    # 4. Register Routers
    dp.include_router(user.router)
    dp.include_router(admin.router)

    # 5. Initialize Neon Postgres Database (schema auto-creation & plan seeding)
    await init_db()

    # 6. Check Seller Configuration and alert admins if missing
    async with async_session() as session:
        from bot.services.seller_service import SellerService
        from bot.keyboards.inline import get_admin_seller_alert_keyboard
        seller_service = SellerService(session)
        has_sellers = await seller_service.has_sellers()
        if not has_sellers:
            logger.warning("No sellers configured in database! Alerting admins and pausing bot for regular users...")
            alert_text = (
                "⚠️ <b>CRITICAL SETUP REQUIRED: Seller Missing!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "No recharge seller username or ID is configured in the bot.\n\n"
                "🛑 <b>The bot will NOT reply to regular users</b> until you configure at least one seller username.\n\n"
                "👉 Click <b>➕ Add Seller Now</b> below or use /admin to add a seller:"
            )
            alert_kb = get_admin_seller_alert_keyboard()
            for admin_id in config.admin_ids:
                try:
                    await bot.send_message(admin_id, alert_text, reply_markup=alert_kb, parse_mode="HTML")
                except Exception as e:
                    logger.warning(f"Could not alert admin {admin_id}: {e}")
        else:
            logger.info("Seller check passed: active sellers found.")

    # 7. Start Polling
    logger.info("Starting Aadhaar Bot...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
