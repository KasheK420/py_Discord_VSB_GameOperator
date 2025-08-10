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

async def _tcp_probe(host: str, port: int, timeout: float = 3.0) -> None:
    """Low-level TCP test so we can separate DNS/refused/timeouts from auth errors."""
    try:
        fut = asyncio.open_connection(host=host, port=port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
    except asyncio.TimeoutError as e:
        raise RuntimeError(f"TCP timeout to {host}:{port}") from e
    except Exception as e:
        # DNS error, refused, unreachable, etc.
        raise RuntimeError(f"TCP connect failed to {host}:{port}: {e}") from e

async def mc_cmd(cmd: str) -> str:
    """One-shot RCON: TCP probe → connect → send → close, with clear error messages."""
    host, port, pwd = settings.MC_RCON_HOST, settings.MC_RCON_PORT, settings.MC_RCON_PASSWORD
    # 1) quick TCP probe
    await _tcp_probe(host, port, timeout=min(_CONNECT_TIMEOUT, 5))
    # 2) RCON connect+cmd
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

# --------- helpers used by the diag command (optional) ---------

def _mask(s: str | None, keep: int = 2) -> str:
    if not s:
        return "<empty>"
    return s[:keep] + "…" + s[-keep:] if len(s) > keep * 2 else "***"

def get_rcon_env() -> dict:
    return {
        "host": settings.MC_RCON_HOST,
        "port": settings.MC_RCON_PORT,
        "password_masked": _mask(settings.MC_RCON_PASSWORD, 2),
    }

async def get_rcon_from_properties() -> dict:
    """Read rcon fields via SFTP so we can compare with ENV."""
    from utils.sftp_client import read_server_properties_text  # lazy import to avoid cycles
    txt = await read_server_properties_text()
    d: dict[str, str] = {}
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        d[k.strip()] = v.strip()
    return {
        "enable_rcon": d.get("enable-rcon"),
        "rcon_port": int(d["rcon.port"]) if "rcon.port" in d and d["rcon.port"].isdigit() else None,
        "rcon_password_set": bool(d.get("rcon.password")),
    }
