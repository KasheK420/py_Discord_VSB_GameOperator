# services/mc_chat_bridge.py
import re
import asyncio
import asyncssh
import discord
from utils.config import settings

CHAT_REGEXES = [
    # [19:33:43] [Server thread/INFO]: <Alice> hello
    re.compile(r": <(?P<name>[^>]+)>\s(?P<msg>.*)$"),
    # Paper/Purpur variants may add colors/markers; add more if needed
]

def setup_chat_bridge(bot: discord.Client):
    async def runner():
        await bot.wait_until_ready()
        chan_id = settings.DISCORD_MC_CHAT_CHANNEL_ID
        log_path = settings.MC_LOG_PATH  # e.g., /home/mc/server/logs/latest.log

        while not bot.is_closed():
            try:
                async with asyncssh.connect(
                    settings.SFTP_HOST,
                    port=settings.SFTP_PORT,
                    username=settings.SFTP_USERNAME,
                    password=settings.SFTP_PASSWORD,
                    known_hosts=None,
                ) as conn:
                    async with conn.create_process(f"tail -n 0 -F {log_path}") as proc:
                        async for raw in proc.stdout:
                            line = raw.strip()
                            name = msg = None
                            for rx in CHAT_REGEXES:
                                m = rx.search(line)
                                if m:
                                    name = m.group("name")
                                    msg = m.group("msg")
                                    break
                            if name and msg:
                                ch = bot.get_channel(chan_id)
                                if isinstance(ch, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
                                    # keep it simple: plain text relay
                                    await ch.send(f"**{name}**: {msg}")
            except asyncio.CancelledError:
                break
            except Exception:
                # wait a moment and reconnect
                await asyncio.sleep(5)

    bot.loop.create_task(runner())
