# services/mc_chat_bridge.py
from __future__ import annotations
import re
import asyncio
import asyncssh
import shlex
import random
import logging
import discord
from utils.config import settings
from utils.sftp_client import sftp_conn  # reuse your existing helper

log = logging.getLogger(__name__)

CHAT_REGEXES = [
    re.compile(r": <(?P<name>[^>]+)>\s(?P<msg>.*)$"),
]

def _resolve_log_path() -> str:
    # Prefer explicit MC_LOG_PATH; otherwise fall back to MC_SERVER_DIR/logs/latest.log
    lp = getattr(settings, "MC_LOG_PATH", "") or ""
    if lp.strip():
        return lp.strip()
    base = (getattr(settings, "MC_SERVER_DIR", "") or "").rstrip("/")
    return f"{base}/logs/latest.log" if base else "logs/latest.log"

async def _check_log_path(path: str) -> tuple[bool, str | None]:
    """Return (exists, error_msg)."""
    try:
        async with sftp_conn() as sftp:
            await sftp.stat(path)  # raises if missing
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

def setup_chat_bridge(bot: discord.Client):
    async def runner():
        await bot.wait_until_ready()
        chan_id = getattr(settings, "DISCORD_MC_CHAT_CHANNEL_ID", 0)
        if not chan_id:
            log.warning("[chat_bridge] DISCORD_MC_CHAT_CHANNEL_ID not set — bridge disabled.")
            return

        path = _resolve_log_path()
        ok, err = await _check_log_path(path)
        if not ok:
            log.error("[chat_bridge] Log path not accessible: %s — %s", path, err or "")
        else:
            log.info("[chat_bridge] Using log path: %s", path)

        backoff = 2.0

        while not bot.is_closed():
            try:
                # Keep the SSH connection alive
                async with asyncssh.connect(
                    settings.SFTP_HOST,
                    port=settings.SFTP_PORT,
                    username=settings.SFTP_USERNAME,
                    password=settings.SFTP_PASSWORD,
                    known_hosts=None,
                    keepalive_interval=30,   # keep the channel alive
                    keepalive_count_max=3,
                ) as conn:
                    # Verify file before tailing (it might rotate/disappear)
                    ok, err = await _check_log_path(path)
                    if not ok:
                        log.warning("[chat_bridge] Log missing at start: %s — %s", path, err or "")
                        await asyncio.sleep(min(backoff, 30))
                        backoff = min(backoff * 1.7, 30)
                        continue
                    backoff = 2.0

                    # Use line-buffered tail; quote path for safety
                    cmd = f"stdbuf -oL -eL tail -n 0 -F -- {shlex.quote(path)}"
                    log.info("[chat_bridge] Starting: %s", cmd)

                    proc = await conn.create_process(cmd)
                    # Concurrently read stderr to catch errors like "No such file"
                    async def _stderr_drain():
                        async for line in proc.stderr:
                            line = line.rstrip("\n")
                            if line:
                                log.warning("[chat_bridge][stderr] %s", line)
                    stderr_task = asyncio.create_task(_stderr_drain())

                    try:
                        async for raw in proc.stdout:
                            line = raw.rstrip("\n")
                            if not line:
                                continue

                            # Parse chat
                            name = msg = None
                            for rx in CHAT_REGEXES:
                                m = rx.search(line)
                                if m:
                                    name = m.group("name")
                                    msg = m.group("msg")
                                    break
                            if name and msg:
                                ch = bot.get_channel(chan_id)
                                if isinstance(ch, (discord.TextChannel, discord.Thread)):
                                    try:
                                        await ch.send(f"**{name}**: {msg}")
                                    except Exception as e:
                                        log.warning("[chat_bridge] Discord send failed: %s", e)
                        # If we exit the async-for, the remote process ended
                        rc = await proc.wait()
                        log.warning("[chat_bridge] tail exited with rc=%s; restarting shortly", rc)
                    finally:
                        stderr_task.cancel()
                        with contextlib.suppress(Exception, asyncio.CancelledError):
                            await stderr_task

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("[chat_bridge] SSH/session error: %s", e)

            # Backoff before reconnect
            await asyncio.sleep(backoff + random.uniform(0, 0.8))
            backoff = min(backoff * 1.7, 30.0)

    # schedule the background task
    bot.loop.create_task(runner())
