from __future__ import annotations
import logging
import os
from typing import Literal

import discord
from discord.ext import commands

log = logging.getLogger(__name__)

ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0"))

class AlertsCog(commands.Cog):
    """Receives events (via FastAPI router) and posts alerts to Discord."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def post_alert(self, kind: Literal["rare_loot","boss","suspicious"], payload: dict):
        ch = self.bot.get_channel(ALERT_CHANNEL_ID)
        if not ch:
            log.warning("Alert channel not found: %s", ALERT_CHANNEL_ID)
            return
        if kind == "rare_loot":
            e = discord.Embed(title="🎁 Rare Loot!", color=0xFFD166)
            e.add_field(name="Player", value=payload.get("player","?"))
            e.add_field(name="Item", value=payload.get("item","?"))
            e.add_field(name="Where", value=payload.get("location","?"))
        elif kind == "boss":
            e = discord.Embed(title="👑 Boss Defeated!", color=0x06D6A0)
            e.add_field(name="Player", value=payload.get("player","?"))
            e.add_field(name="Boss", value=payload.get("boss","?"))
        else:
            e = discord.Embed(title="🛑 Suspicious Activity", color=0xEF476F)
            e.add_field(name="Player", value=payload.get("player","?"))
            e.add_field(name="Details", value=payload.get("details","?"), inline=False)
        await ch.send(embed=e)

async def setup(bot):
    await bot.add_cog(AlertsCog(bot))