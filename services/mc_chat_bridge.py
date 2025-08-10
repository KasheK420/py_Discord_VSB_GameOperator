# services/mc_chat_bridge.py
from __future__ import annotations
import re
import asyncio
import logging
from typing import Optional

import discord
from utils.config import settings
from utils.sftp_client import sftp_conn  # reuse your SFTP helper

log = logging.getLogger(__name__)

CHAT_REGEXES = [
    # [19:33:43] [Server thread/INFO]: <Alice> hello
    re.compile(r": <(?P<name>[^>]+)>\s(?P<msg>.*)$"),
]

def _resolve_log_path() -> str:
    lp = (getattr(settings, "MC_LOG_PATH", "") or "").strip()
    if lp:
        return lp
    base = (getattr(settings, "MC_SERVER_DIR", "") or "").rstrip("/")
    return f"{base}/logs/latest.log" if base else "logs/latest.log"

async def _stat_safe(path: str) -> Optional[int]:
    """Return remote file size or None."""
    try:
        async with sftp_conn() as sftp:
            st = await sftp.stat(path)
            return int(getattr(st, "size", 0))
    except Exception:
        return None

def setup_chat_bridge(bot: discord.Client):
    async def runner():
        await bot.wait_until_ready()
        chan_id = getattr(settings, "DISCORD_MC_CHAT_CHANNEL_ID", 0)
        if not chan_id:
            log.warning("[chat_bridge] DISCORD_MC_CHAT_CHANNEL_ID not set — bridge disabled.")
            return

        path = _resolve_log_path()
        log.info("[chat_bridge] Using log path: %s", path)

        # tail state
        offset = 0
        buf = ""  # for partial lines
        poll = max(0.8, getattr(settings, "POLL_INTERVAL_SECONDS", 1))

        while not bot.is_closed():
            try:
                async with sftp_conn() as sftp:
                    # Try opening; if it fails, wait and retry
                    try:
                        f = await sftp.open(path, "r")
                    except Exception as e:
                        log.warning("[chat_bridge] open failed (%s). Retrying…", e)
                        await asyncio.sleep(2.0)
                        continue

                    async with f:
                        # Initialize offset to EOF on first run to avoid dumping old history
                        if offset == 0:
                            try:
                                st = await sftp.stat(path)
                                offset = int(getattr(st, "size", 0))
                            except Exception:
                                offset = 0

                        await f.seek(offset)
                        while not bot.is_closed():
                            chunk = await f.read(64 * 1024)
                            if not chunk:
                                # No new data — check for rotation (size shrank)
                                try:
                                    st = await sftp.stat(path)
                                    size_now = int(getattr(st, "size", 0))
                                except Exception:
                                    size_now = None

                                if size_now is not None and size_now < offset:
                                    # rotated/truncated
                                    log.info("[chat_bridge] log rotated/truncated; resetting offset")
                                    offset = 0
                                    await f.seek(0)

                                await asyncio.sleep(poll)
                                continue

                            text = chunk.decode(errors="replace")
                            offset += len(chunk)

                            buf += text
                            *lines, buf = buf.split("\n")
                            if lines:
                                ch = bot.get_channel(chan_id)
                                if isinstance(ch, (discord.TextChannel, discord.Thread)):
                                    for line in lines[-50:]:  # avoid bursts
                                        m = None
                                        for rx in CHAT_REGEXES:
                                            m = rx.search(line)
                                            if m: break
                                        if m:
                                            name = m.group("name"); msg = m.group("msg")
                                            try:
                                                await ch.send(f"**{name}**: {msg}")
                                            except Exception as e:
                                                log.warning("[chat_bridge] Discord send failed: %s", e)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("[chat_bridge] SFTP tail error: %s", e)
                await asyncio.sleep(2.0)

    bot.loop.create_task(runner())
