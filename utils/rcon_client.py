# utils/rcon_client.py
from __future__ import annotations
import asyncio
import contextlib
import logging
from aiomcrcon import Client
from utils.config import settings

log = logging.getLogger(__name__)

_CONNECT_TIMEOUT = int(getattr(settings, "RCON_CONNECT_TIMEOUT", 5))
_CMD_TIMEOUT = int(getattr(settings, "RCON_CMD_TIMEOUT", 8))

async def mc_cmd(cmd: str) -> str:
    """Connect → send → close (no persistent session)."""
    host, port, pwd = settings.MC_RCON_HOST, settings.MC_RCON_PORT, settings.MC_RCON_PASSWORD
    c = Client(host, port, pwd)
    try:
        await asyncio.wait_for(c.connect(), timeout=_CONNECT_TIMEOUT)
        return await asyncio.wait_for(c.send_cmd(cmd), timeout=_CMD_TIMEOUT)
    finally:
        with contextlib.suppress(Exception):
            await c.close()

async def get_status() -> dict:
    """Return parsed status from `list`."""
    out = await mc_cmd("list")
    online = 0
    maxp = 0
    players: list[str] = []
    try:
        parts = out.split("players online:")
        head = parts[0]
        tail = parts[1] if len(parts) > 1 else ""
        nums = [int(s) for s in head.split() if s.isdigit()]
        if len(nums) >= 2:
            online, maxp = nums[0], nums[1]
        players = [p.strip() for p in tail.split(",") if p.strip()]
    except Exception:
        pass
    return {"raw": out, "online": online, "max": maxp, "players": players}
