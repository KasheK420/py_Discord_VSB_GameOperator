import asyncio
from contextlib import asynccontextmanager
from aiomcrcon import Client
from utils.config import settings

@asynccontextmanager
async def rcon_client(host: str | None = None, port: int | None = None, password: str | None = None):
    h = host or settings.MC_RCON_HOST
    p = port or settings.MC_RCON_PORT
    pw = password or settings.MC_RCON_PASSWORD
    client = Client(h, p, pw)
    await client.connect()
    try:
        yield client
    finally:
        await asyncio.sleep(0)  # let pending tasks flush
        await client.close()

async def mc_cmd(cmd: str) -> str:
    async with rcon_client() as c:
        return await c.send(cmd)

async def get_status() -> dict:
    # Many Spigot/Paper servers have the `list` command; `minecraft:execute` avoided here.
    out = await mc_cmd("list")
    # Example: "There are 2 of a max of 20 players online: Alice, Bob"
    # Parse defensively:
    online = 0; maxp = 0; players = []
    try:
        # crude parse
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
