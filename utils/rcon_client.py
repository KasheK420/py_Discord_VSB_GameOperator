# utils/rcon_client.py
import asyncio
from aiomcrcon import Client
from utils.config import settings

class RconManager:
    def __init__(self):
        self._client: Client | None = None
        self._lock = asyncio.Lock()
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._keep_task: asyncio.Task | None = None

    async def start(self):
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._stop.set()
        self._ready.clear()
        if self._keep_task:
            self._keep_task.cancel()
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
        if self._task:
            try:
                await self._task
            except Exception:
                pass

    async def _run(self):
        backoff = 1.0
        while not self._stop.is_set():
            try:
                c = Client(settings.MC_RCON_HOST, settings.MC_RCON_PORT, settings.MC_RCON_PASSWORD)
                await c.connect()
                self._client = c
                self._ready.set()
                backoff = 1.0  # reset on success
                # keepalive pinger
                self._keep_task = asyncio.create_task(self._keepalive())
                # wait until asked to stop or connection drops
                await self._stop.wait()
            except Exception:
                self._ready.clear()
                self._client = None
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                if self._keep_task:
                    self._keep_task.cancel()
                    self._keep_task = None
                if self._client:
                    try:
                        await self._client.close()
                    except Exception:
                        pass
                    self._client = None
        self._ready.clear()

    async def _keepalive(self):
        # ping server periodically; harmless command that always exists
        while True:
            try:
                await asyncio.sleep(getattr(settings, "RCON_KEEPALIVE_SECONDS", 30))
                if self._client:
                    await self._client.send_cmd("list")
            except asyncio.CancelledError:
                raise
            except Exception:
                # connection will be retried by _run loop once a command fails/close happens
                await asyncio.sleep(2)

    async def send(self, cmd: str) -> str:
        # waits until connected; then sends a command
        await self._ready.wait()
        async with self._lock:
            if not self._client:
                raise RuntimeError("RCON not connected")
            return await self._client.send_cmd(cmd)

_manager = RconManager()

async def start_rcon_manager():
    await _manager.start()

async def stop_rcon_manager():
    await _manager.stop()

async def mc_cmd(cmd: str) -> str:
    return await _manager.send(cmd)

async def get_status() -> dict:
    out = await mc_cmd("list")
    online = 0; maxp = 0; players = []
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
