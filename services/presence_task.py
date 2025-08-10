# services/presence_task.py
import asyncio
import discord
from utils.config import settings
from utils.rcon_client import get_status

def setup_presence_tasks(bot):
    async def updater():
        await bot.wait_until_ready()
        vc_id = settings.DISCORD_VOICE_CHANNEL_ID
        server_name = settings.MC_SERVER_NAME  # <— new

        while not bot.is_closed():
            try:
                status = await get_status()  # {"online": int, "max": int, ...}
                # Desired format: "<server name> X/X"
                target_name = f"{server_name} {status['online']}/{status['max']}"

                vc = bot.get_channel(vc_id)
                if isinstance(vc, discord.VoiceChannel):
                    # Discord channel names have a 100-char limit; be safe:
                    safe_name = target_name[:100]
                    if vc.name != safe_name:
                        await vc.edit(name=safe_name)

                # Optional: also set bot presence to show just X players
                act = discord.Activity(
                    type=discord.ActivityType.watching,
                    name=f"{status['online']} players"
                )
                await bot.change_presence(activity=act)

            except Exception:
                # swallow errors; next tick will retry
                pass

            await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)

    bot.loop.create_task(updater())
