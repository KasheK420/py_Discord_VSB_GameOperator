from __future__ import annotations
import logging
import os
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.permissions import guild_only
from db.models_game import AccountLink
from utils.db import async_session_maker

log = logging.getLogger(__name__)

class RoleSyncCog(commands.Cog):
    """Link Minecraft <-> Discord and sync roles based on in-game rank."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.guild_id = int(os.getenv("GUILD_ID", "0"))
        self.sync_roles.start()

    def cog_unload(self):
        self.sync_roles.cancel()

    @app_commands.command(name="link", description="Link your Minecraft account to your Discord account")
    @app_commands.describe(ign="Your Minecraft username")
    async def link(self, interaction: discord.Interaction, ign: str):
        async with async_session_maker() as s:
            rec = await AccountLink.upsert(s, discord_id=interaction.user.id, ign=ign)
        await interaction.response.send_message(f"Linked **{ign}** to {interaction.user.mention}.", ephemeral=True)

    @app_commands.command(name="unlink", description="Unlink your Minecraft account")
    async def unlink(self, interaction: discord.Interaction):
        async with async_session_maker() as s:
            await AccountLink.delete_by_discord(s, interaction.user.id)
        await interaction.response.send_message("Unlinked.", ephemeral=True)

    @tasks.loop(minutes=10)
    async def sync_roles(self):
        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            return
        # NOTE: Replace with your real rank source (API/RCON). Here we stub as {ign: rank_name}
        async with async_session_maker() as s:
            links = await AccountLink.fetch_all(s)
        for link in links:
            member = guild.get_member(link.discord_id)
            if not member:
                continue
            desired_role_name = await self._get_rank_for_ign(link.ign)
            if not desired_role_name:
                continue
            # Find or create the role
            role = discord.utils.get(guild.roles, name=desired_role_name)
            if not role:
                try:
                    role = await guild.create_role(name=desired_role_name, mentionable=False)
                except discord.Forbidden:
                    log.warning("Cannot create role %s", desired_role_name)
                    continue
            # Ensure member has it; remove other rank-roles if needed
            to_remove = [r for r in member.roles if r.name.startswith("Rank:") and r != role]
            try:
                if role not in member.roles:
                    await member.add_roles(role, reason="Rank sync")
                if to_remove:
                    await member.remove_roles(*to_remove, reason="Rank cleanup")
            except discord.Forbidden:
                log.warning("Missing perms to edit roles for %s", member)

    async def _get_rank_for_ign(self, ign: str) -> Optional[str]:
        # TODO: wire to real data. For demo: hash username to a rank
        ranks = ["Rank:Newbie", "Rank:Member", "Rank:VIP", "Rank:Mod"]
        idx = abs(hash(ign)) % len(ranks)
        return ranks[idx]

async def setup(bot):
    await bot.add_cog(RoleSyncCog(bot))