import asyncio
import discord
import logging

from utils.config import settings
from utils.rcon_client import get_status

log = logging.getLogger(__name__)

def setup_presence_tasks(bot):
    # prevent duplicates
    if getattr(bot, "_presence_started", False):
        log.info("presence task already started; skipping")
        return

    async def updater():
        try:
            # make sure gateway is ready
            await bot.wait_until_ready()
            log.info("presence updater started")
            while not bot.is_closed():
                # TODO: your presence logic here, e.g.:
                # await bot.change_presence(activity=discord.Game(name="VŠB GameOperator"))
                await asyncio.sleep(300)  # every 5 min
        except asyncio.CancelledError:
            log.info("presence updater cancelled")
        except Exception:
            log.exception("presence updater crashed")

    # discord.py 2.x: no bot.loop — use the running loop
    asyncio.create_task(updater())
    bot._presence_started = True
    log.info("queued presence updater task")