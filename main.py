# main.py
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import sys
import time
from importlib import import_module

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from fastapi import FastAPI

import discord
from discord.ext import commands

# silence PyNaCl warning (no voice support needed)
discord.VoiceClient.warn_nacl = False

# --- project utils
from utils.config import settings
from utils.logging import configure_logging
from utils.db import async_engine, async_session_maker  # noqa: F401

from services.mc_chat_bridge import setup_chat_bridge
from services.minecraft_cog import MinecraftCog
from services.moderation_cog import ModerationCog
from services.presence_task import setup_presence_tasks

# ---------- logging
configure_logging(settings.LOG_LEVEL)
log = logging.getLogger("main")
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

# scrub proxy vars which sometimes cause odd DNS timeouts in containers
for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
            "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
    os.environ.pop(var, None)


def _mask_token(tok: str | None) -> str:
    if not tok:
        return "<empty>"
    if len(tok) <= 8:
        return "***"
    return tok[:4] + "…" + tok[-4:]


def _sanitize_db_url(url: str) -> str:
    # postgresql+asyncpg://user:pass@host:5432/db -> mask password
    return re.sub(r"://([^:/]+):([^@]+)@", r"://\1:***@", url)


# ---------- discord bot
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True


class MyBot(commands.Bot):
    async def setup_hook(self) -> None:
        log.info("[discord] setup_hook: loading cogs & presence")
        await self.add_cog(MinecraftCog(self))
        await self.add_cog(ModerationCog(self))
        await self.load_extension("services.portal_cog")

        setup_presence_tasks(self)
        setup_chat_bridge(self)

        try:
            await self.tree.sync()  # or use guild-scoped sync for faster propagation
            log.info("[discord] slash commands synced")
        except Exception:
            log.exception("[discord] slash sync failed")


bot = MyBot(
    command_prefix=settings.DISCORD_COMMAND_PREFIX,
    intents=intents,
)

# extra visibility on discord lifecycle
@bot.event
async def on_connect():
    log.info("[discord] on_connect")


@bot.event
async def on_ready():
    guilds = [g.name for g in bot.guilds]
    log.info(
        "[discord] on_ready as %s (latency=%sms, guilds=%s)",
        bot.user,
        int(bot.latency * 1000) if bot.latency else "n/a",
        guilds,
    )


@bot.event
async def on_resumed():
    log.info("[discord] on_resumed")


@bot.event
async def on_disconnect():
    log.warning("[discord] on_disconnect")


# ---------- app
app = FastAPI(title="VSB GameOperator")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "started": bool(getattr(app.state, "started", False)),
        "discord_task": getattr(app.state, "bot_task", None) is not None,
        "discord_logged_in": bot.user is not None,
    }


@app.get("/debug/state")
async def debug_state():
    return {
        "pid": os.getpid(),
        "python": sys.version,
        "db_url": _sanitize_db_url(settings.database_url),
        "discord_token_set": bool(getattr(settings, "DISCORD_TOKEN", None) or os.environ.get("DISCORD_TOKEN")),
        "intents": {
            "message_content": intents.message_content,
            "guilds": intents.guilds,
            "members": intents.members,
        },
    }


# ---------- DB utils

async def _ping() -> None:
    """Single DB round-trip to verify DNS, TCP, auth, and query."""
    async with async_engine.begin() as conn:
        await conn.execute(text("SELECT 1"))


async def _db_ping(timeout: float = 10.0, attempts: int = 6) -> None:
    """Retry DB ping with exponential backoff."""
    delay = 1.0
    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            await asyncio.wait_for(_ping(), timeout=timeout)
            log.info("DB ping OK on attempt %d", i)
            return
        except Exception as e:
            last = e
            log.warning("DB ping attempt %d failed: %s; retrying in %.1fs", i, e, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 8.0)
    assert last is not None
    raise last


async def _import_models() -> "Base":
    """
    Import Base and model modules so metadata is populated,
    handling both 'models.*' and top-level files.
    """
    base_mod = None
    try:
        base_mod = import_module("models.base")
    except ModuleNotFoundError:
        base_mod = import_module("base")

    # Import model modules (add more here if you add files)
    for name in ("models.events", "models.server", "events", "server"):
        with contextlib.suppress(ModuleNotFoundError):
            import_module(name)

    Base = getattr(base_mod, "Base")
    return Base


async def _create_all(engine: AsyncEngine) -> None:
    """Create tables if they don't exist yet."""
    Base = await _import_models()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info("DB schema ensured (create_all).")
    except SQLAlchemyError:
        log.exception("DB create_all failed.")
        raise


# ---------- lifecycle

@app.on_event("startup")
async def on_startup():
    if getattr(app.state, "started", False):
        log.info("Startup already executed; skipping.")
        return

    t0 = time.perf_counter()
    log.info("Starting up… pid=%s, py=%s", os.getpid(), sys.version.split()[0])
    log.info("DB=%s", _sanitize_db_url(settings.database_url))
    token = getattr(settings, "DISCORD_TOKEN", None) or os.environ.get("DISCORD_TOKEN")
    log.info("Discord token present=%s (%s)", bool(token), _mask_token(token))

    # 1) DB ping + create tables
    try:
        t = time.perf_counter()
        log.info("[1/3] DB ping…")
        await _db_ping(timeout=10.0)
        log.info("[1/3] DB ping OK in %.2fs", time.perf_counter() - t)

        t = time.perf_counter()
        log.info("[2/3] Ensuring DB schema (create_all)…")
        await _create_all(async_engine)
        log.info("[2/3] DB schema OK in %.2fs", time.perf_counter() - t)
    except Exception as e:
        log.exception("DB init failed (continuing so Discord can still run): %s", e)

    # 2) Start Discord (non-blocking) + watchdog
    if not token:
        log.error("[3/3] DISCORD_TOKEN not set; skip bot start.")
    else:
        if getattr(app.state, "bot_task", None) is None:
            log.info("[3/3] Starting Discord client task…")
            app.state.bot_task = asyncio.create_task(_start_bot(token))
            asyncio.create_task(_discord_login_watchdog(20.0))
        else:
            log.info("[3/3] Discord task already present; skip start.")

    app.state.started = True
    log.info("Startup complete in %.2fs", time.perf_counter() - t0)


async def _start_bot(token: str):
    try:
        await bot.start(token)
    except discord.LoginFailure as e:
        log.exception("[discord] Login failed: %s", e)
    except asyncio.CancelledError:
        pass
    except Exception:
        log.exception("[discord] Unexpected exception in bot task")


async def _discord_login_watchdog(seconds: float):
    await asyncio.sleep(seconds)
    if bot.user is None:
        log.warning(
            "[discord] Not logged in after %.0fs. Check token / gateway / intents / network.",
            seconds,
        )


@app.on_event("shutdown")
async def on_shutdown():
    log.info("Shutting down…")
    # Stop Discord
    bot_task = getattr(app.state, "bot_task", None)
    if not bot.is_closed():
        with contextlib.suppress(Exception):
            await bot.close()
    if bot_task and not bot_task.done():
        bot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bot_task
    # Dispose DB
    with contextlib.suppress(Exception):
        await async_engine.dispose()
    log.info("Shutdown complete.")
