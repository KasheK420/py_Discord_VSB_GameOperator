from __future__ import annotations
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from db.models_game import PlayerStats
from utils.db import async_session_maker

log = logging.getLogger(__name__)

class StatsCog(commands.Cog):
    """/stats and /leaderboard commands."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="stats", description="Show player stats")
    @app_commands.describe(player="Minecraft username")
    async def stats(self, interaction: discord.Interaction, player: str):
        async with async_session_maker() as s:
            st = await PlayerStats.fetch_one(s, player)
        if not st:
            return await interaction.response.send_message(f"No stats for **{player}**.", ephemeral=True)
        e = discord.Embed(title=f"Stats for {player}", color=0x2b88d8)
        e.add_field(name="Kills", value=st.kills)
        e.add_field(name="Deaths", value=st.deaths)
        e.add_field(name="Playtime (h)", value=round(st.playtime_hours, 1))
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="leaderboard", description="Top players")
    @app_commands.describe(metric="Which metric to rank by")
    async def leaderboard(self, interaction: discord.Interaction, metric: discord.app_commands.Choice[str]):
        metric_key = metric.value
        async with async_session_maker() as s:
            rows = await PlayerStats.top(s, metric_key, limit=10)
        lines = [f"**#{i+1}** {r.player}: {getattr(r, metric_key)}" for i, r in enumerate(rows)]
        embed = discord.Embed(title=f"Leaderboard – {metric_key}", description="\n".join(lines) or "No data", color=0x7289DA)
        await interaction.response.send_message(embed=embed)

    @leaderboard.autocomplete("metric")
    async def _lb_metric_ac(self, interaction: discord.Interaction, current: str):
        options = [
            app_commands.Choice(name="kills", value="kills"),
            app_commands.Choice(name="deaths", value="deaths"),
            app_commands.Choice(name="playtime_hours", value="playtime_hours"),
        ]
        return [o for o in options if current.lower() in o.name.lower()][:5]

async def setup(bot):
    await bot.add_cog(StatsCog(bot))