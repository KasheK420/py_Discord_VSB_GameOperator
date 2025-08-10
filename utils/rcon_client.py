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
_KEEPALIVE_SECONDS = int(getattr(settings, "RCON_KEEPALIVE_SECONDS", 30))

class RconManager:
    def __init__(self):
        self._client: Client | None = None
        self._lock = asyncio.Lock()
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="rcon-manager")

    async def stop(self) -> None:
        self._stop.set()
        self._ready.clear()
        if self._task:
            with contextlib.suppress(Exception):
                await self._task
        await self._close_client()

    async def _close_client(self):
        if self._client:
            with contextlib.suppress(Exception):
                await self._client.close()
        self._client = None
        self._ready.clear()

    async def _connect_once(self) -> Client:
        host, port = settings.MC_RCON_HOST, settings.MC_RCON_PORT
        log.info("[rcon] connecting to %s:%s …", host, port)
        c = Client(host, port, settings.MC_RCON_PASSWORD)
        await asyncio.wait_for(c.connect(), timeout=_CONNECT_TIMEOUT)
        log.info("[rcon] connected to %s:%s", host, port)
        return c

    async def _run(self):
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._client = await self._connect_once()
                self._ready.set()
                backoff = 1.0

                # keepalive loop: send "list" every N seconds; any error triggers reconnect
                while not self._stop.is_set():
                    try:
                        try:
                            await asyncio.wait_for(self._stop.wait(), timeout=_KEEPALIVE_SECONDS)
                            break  # stop requested
                        except asyncio.TimeoutError:
                            pass
                        # keepalive
                        async with self._lock:
                            if not self._client:
                                raise RuntimeError("client missing")
                            await asyncio.wait_for(self._client.send_cmd("list"), timeout=_CMD_TIMEOUT)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        log.warning("[rcon] keepalive failed: %s (will reconnect)", e)
                        raise

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("[rcon] connection error: %s; retrying in %.1fs", e, backoff)
                await self._close_client()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.7, 30.0)
            else:
                # clean stop
                break

        await self._close_client()
        log.info("[rcon] manager stopped")

    async def send(self, cmd: str) -> str:
        """
        Send a command via the persistent connection.
        If the manager isn't ready within _CONNECT_TIMEOUT, fall back to a one-shot connect.
        """
        # Ensure background manager is running
        await self.start()

        # Wait briefly for readiness
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=_CONNECT_TIMEOUT)
        except asyncio.TimeoutError:
            log.warning("[rcon] manager not ready in %ss; using one-shot connection", _CONNECT_TIMEOUT)
            return await _oneshot_send(cmd)

        # Use persistent client
        async with self._lock:
            if not self._client:
                # Shouldn't happen, but handle gracefully
                log.warning("[rcon] client lost; using one-shot connection")
                return await _oneshot_send(cmd)
            try:
                return await asyncio.wait_for(self._client.send_cmd(cmd), timeout=_CMD_TIMEOUT)
            except Exception as e:
                log.warning("[rcon] command failed: %s; forcing reconnect", e)
                # Force reconnect by closing and clearing readiness
                await self._close_client()
                # Kick the background loop to reconnect (it’s still running)
                return await _oneshot_send(cmd)

# ---- one-shot fallback (connect → send → close) --------------------

async def _oneshot_send(cmd: str) -> str:
    host, port = settings.MC_RCON_HOST, settings.MC_RCON_PORT
    log.info("[rcon/oneshot] %s:%s → %s", host, port, cmd)
    c = Client(host, port, settings.MC_RCON_PASSWORD)
    try:
        await asyncio.wait_for(c.connect(), timeout=_CONNECT_TIMEOUT)
        return await asyncio.wait_for(c.send_cmd(cmd), timeout=_CMD_TIMEOUT)
    finally:
        with contextlib.suppress(Exception):
            await c.close()

# ---- public API ----------------------------------------------------

_manager = RconManager()

async def start_rcon_manager():
    await _manager.start()

async def stop_rcon_manager():
    await _manager.stop()

async def mc_cmd(cmd: str) -> str:
    return await _manager.send(cmd)

async def get_status() -> dict:
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
