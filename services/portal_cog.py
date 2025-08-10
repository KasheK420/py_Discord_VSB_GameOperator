from __future__ import annotations
import logging
import discord
from discord.ext import commands
from discord import app_commands
from utils.config import settings
from utils.rcon_client import get_status  # used by the Status button

log = logging.getLogger(__name__)

# ----- helpers ---------------------------------------------------------------

def _is_mod(inter: discord.Interaction) -> bool:
    uid_roles = {r.id for r in getattr(inter.user, "roles", [])}
    allowed = (
        set(settings.roles_from_csv(settings.DISCORD_ADMIN_ROLE_IDS))
        | set(settings.roles_from_csv(settings.DISCORD_MOD_ROLE_IDS))
        | set(settings.roles_from_csv(getattr(settings, "DISCORD_SERVER_MOD_ROLE_IDS", "")))
    )
    return bool(uid_roles & allowed)

def _admin_mentions() -> str:
    ids = []
    ids += settings.roles_from_csv(settings.DISCORD_ADMIN_ROLE_IDS)
    ids += settings.roles_from_csv(settings.DISCORD_MOD_ROLE_IDS)
    return " ".join(f"<@&{rid}>" for rid in ids) or "@here"

# ----- modal + view ----------------------------------------------------------

class WhitelistModal(discord.ui.Modal, title="Minecraft Whitelist Request"):
    ign = discord.ui.TextInput(label="Minecraft username", placeholder="e.g. Steve", max_length=32)
    notes = discord.ui.TextInput(label="Notes (optional)", style=discord.TextStyle.paragraph, required=False, max_length=300)

    def __init__(self, on_submit_cb):
        super().__init__()
        self._cb = on_submit_cb

    async def on_submit(self, interaction: discord.Interaction):
        await self._cb(interaction, str(self.ign), str(self.notes or ""))

class PortalView(discord.ui.View):
    """Persistent view with three buttons."""
    def __init__(self):
        super().__init__(timeout=None)  # persistent across restarts

    @discord.ui.button(label="Request Whitelist", style=discord.ButtonStyle.primary, custom_id="portal:whitelist")
    async def whitelist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WhitelistModal(on_submit_cb=self._handle_wl_submit))

    @discord.ui.button(label="Server Status", style=discord.ButtonStyle.secondary, custom_id="portal:status")
    async def status_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            status = await get_status()  # {"online": int, "max": int, "players": [...]}
            e = discord.Embed(title="Server Status", color=0x2b88d8)
            e.add_field(name="Online", value=f"{status.get('online','?')}/{status.get('max','?')}", inline=True)
            players = ", ".join(status.get("players") or []) or "—"
            e.add_field(name="Players", value=players, inline=True)
            await interaction.response.send_message(embed=e, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Status error: `{e}`", ephemeral=True)

    @discord.ui.button(label="Request Support", style=discord.ButtonStyle.success, custom_id="portal:support")
    async def support_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
            return await interaction.response.send_message("Run this in a text channel.", ephemeral=True)
        try:
            thread = await channel.create_thread(
                name=f"support-{interaction.user.name}-{interaction.user.id}",
                type=discord.ChannelType.private_thread
            )
            await thread.add_user(interaction.user)
            await thread.send(f"{_admin_mentions()} New support request by {interaction.user.mention}.")
            await interaction.response.send_message(f"Created {thread.mention}", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I need permission to create **private threads** here.", ephemeral=True)

    async def _handle_wl_submit(self, interaction: discord.Interaction, ign: str, notes: str):
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
            return await interaction.response.send_message("Run this in a text channel.", ephemeral=True)
        try:
            thread = await channel.create_thread(
                name=f"whitelist-{ign}-{interaction.user.id}",
                type=discord.ChannelType.private_thread
            )
            await thread.add_user(interaction.user)
            await thread.send(
                f"{_admin_mentions()} Whitelist request\n"
                f"• Player: **{ign}**\n"
                f"• Requester: {interaction.user.mention}\n"
                f"• Notes: {notes or '—'}"
            )
            await interaction.response.send_message(f"Thanks! Created {thread.mention}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I need permission to create **private threads** here.", ephemeral=True)

# ----- cog -------------------------------------------------------------------

class PortalCog(commands.Cog):
    """Slash command to drop a portal message with buttons, plus persistent handlers."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        # register persistent handlers once per process
        self.bot.add_view(PortalView())
        log.info("[portal] persistent view registered")

    @app_commands.command(name="portal", description="Post portal buttons (whitelist / status / support)")
    async def portal(self, interaction: discord.Interaction):
        if not _is_mod(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        embed = discord.Embed(
            title="Server Portal",
            description=(
                "• Add yourself to whitelist\n"
                "• Check server status\n"
                "• Request help\n\n"
                "Use the buttons below."
            ),
            color=0x5865F2,
        )
        await interaction.response.send_message(embed=embed, view=PortalView())

async def setup(bot: commands.Bot):
    await bot.add_cog(PortalCog(bot))
