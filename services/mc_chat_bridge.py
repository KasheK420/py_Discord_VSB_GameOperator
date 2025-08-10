# services/mc_chat_bridge.py
from __future__ import annotations
import asyncio
import logging
import re
from typing import Optional

import discord
from utils.config import settings
from utils.sftp_client import sftp_conn

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

async def _remote_size(path: str) -> Optional[int]:
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

        offset = 0
        buf = ""
        poll = max(1.0, getattr(settings, "POLL_INTERVAL_SECONDS", 15))

        while not bot.is_closed():
            try:
                async with sftp_conn() as sftp:
                    try:
                        f = await sftp.open(path, "r")
                    except Exception as e:
                        log.warning("[chat_bridge] open(%s) failed: %s — retrying…", path, e)
                        await asyncio.sleep(2.0)
                        continue

                    async with f:
                        # start from EOF so we don't spam old history
                        if offset == 0:
                            sz = await _remote_size(path)
                            offset = int(sz or 0)
                            await f.seek(offset)

                        while not bot.is_closed():
                            chunk = await f.read(64 * 1024)
                            if not chunk:
                                # rotation/truncation check
                                sz = await _remote_size(path)
                                if sz is not None and sz < offset:
                                    log.info("[chat_bridge] log rotated/truncated; resetting offset")
                                    offset = 0
                                    await f.seek(0)
                                await asyncio.sleep(poll)
                                continue

                            # normalize to str
                            if isinstance(chunk, bytes):
                                text = chunk.decode("utf-8", errors="replace")
                            else:
                                text = chunk  # already str
                            offset += len(chunk if isinstance(chunk, (bytes, bytearray)) else text.encode("utf-8", errors="ignore"))

                            buf += text
                            *lines, buf = buf.split("\n")
                            if not lines:
                                continue

                            ch = bot.get_channel(chan_id)
                            if not isinstance(ch, (discord.TextChannel, discord.Thread)):
                                continue

                            # parse & send
                            for line in lines[-50:]:
                                m = None
                                for rx in CHAT_REGEXES:
                                    m = rx.search(line)
                                    if m:
                                        break
                                if not m:
                                    continue
                                name = m.group("name")
                                msg = m.group("msg")
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
