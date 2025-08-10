# services/portal_cog.py
from __future__ import annotations
import asyncio
import contextlib
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.config import settings
from utils.rcon_client import get_status, mc_cmd
from utils.sftp_client import read_server_properties_text, list_plugins

log = logging.getLogger(__name__)

# ---- static server manual (as requested) ----
ICON_URL = "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcStUAvKkP38bvaD2f4clomJAyu2detk5pfk5A&s"
SRV_NAME = "VSB - Minecraft Classic"
SRV_DNS  = "mc.vsb-discord.cz"
SRV_IP   = "167.235.90.82"
SRV_PORT = 31095

def _csv_ids(val: str) -> list[int]:
    return [int(x.strip()) for x in str(val or "").split(",") if x.strip().isdigit()]

PORTAL_CHANNEL_ID = int(getattr(settings, "PORTAL_CHANNEL_ID", 1404017766922715226))
WHITELIST_ALLOWED_ROLE_IDS = _csv_ids(getattr(settings, "DISCORD_WHITELIST_ALLOWED_ROLE_IDS", ""))
ADMIN_ROLE_IDS = (
    _csv_ids(getattr(settings, "DISCORD_ADMIN_ROLE_IDS", "")) +
    _csv_ids(getattr(settings, "DISCORD_MOD_ROLE_IDS", ""))
)

def _admin_mentions() -> str:
    return " ".join(f"<@&{rid}>" for rid in ADMIN_ROLE_IDS) or "@here"

def _has_any_role(member: discord.Member | discord.abc.User, role_ids: list[int]) -> bool:
    if not role_ids:
        return True
    if not isinstance(member, discord.Member):
        return False
    uroles = {r.id for r in member.roles}
    return any(rid in uroles for rid in role_ids)

async def _ack(inter: discord.Interaction, ephemeral: bool = True):
    if not inter.response.is_done():
        await inter.response.defer(ephemeral=ephemeral, thinking=True)

def _portal_embed(server_info: Optional[dict] = None, props_small: Optional[dict] = None) -> discord.Embed:
    e = discord.Embed(
        title="🎮 Minecraft Server",
        description="Use the buttons below.",
        color=0x5865F2,
    )
    e.set_thumbnail(url=ICON_URL)

    # Manual connection info
    conn_lines = [f"**Name:** {SRV_NAME}",
                  f"**DNS:** `{SRV_DNS}`",
                  f"**IP:** `{SRV_IP}`",
                  f"**Port:** `{SRV_PORT}`",
                  f"**Quick:** `{SRV_DNS}:{SRV_PORT}`"]
    e.add_field(name="Connection", value="\n".join(conn_lines), inline=False)

    if server_info:
        players = ", ".join(server_info.get("players") or []) or "—"
        e.add_field(name="Online", value=f"{server_info.get('online','?')}/{server_info.get('max','?')}", inline=True)
        e.add_field(name="Players", value=players, inline=True)
        if "error" in server_info:
            e.add_field(name="Status Error", value=f"`{server_info['error']}`", inline=False)

    if props_small:
        pretty = "\n".join(f"**{k}**: {v}" for k, v in props_small.items())
        if pretty:
            e.add_field(name="Properties (key fields)", value=pretty, inline=False)

    e.set_footer(text="GameOperator Portal")
    return e

# ------------------------------ Modals ------------------------------

class WhitelistModal(discord.ui.Modal, title="Whitelist Request"):
    ign = discord.ui.TextInput(label="Minecraft username", max_length=32)
    note = discord.ui.TextInput(label="Notes (optional)", style=discord.TextStyle.paragraph, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        await _ack(interaction)
        if not _has_any_role(interaction.user, WHITELIST_ALLOWED_ROLE_IDS):
            return await interaction.followup.send("You don’t have permission to request whitelist.", ephemeral=True)
        player = str(self.ign).strip()
        try:
            await asyncio.wait_for(mc_cmd(f"whitelist add {player}"), timeout=8)
            await asyncio.wait_for(mc_cmd("whitelist reload"), timeout=8)
            await interaction.followup.send(f"✅ Added **{player}** to whitelist.", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("❌ RCON timed out (check reachability).", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ RCON error: `{e}`", ephemeral=True)

class SupportModal(discord.ui.Modal, title="Contact Admin"):
    subject = discord.ui.TextInput(label="Subject", max_length=80)
    details = discord.ui.TextInput(label="What do you need?", style=discord.TextStyle.paragraph, max_length=1000)
    async def on_submit(self, interaction: discord.Interaction):
        await _ack(interaction)
        ch = interaction.channel
        if not isinstance(ch, discord.TextChannel):
            return await interaction.followup.send("Run in a text channel.", ephemeral=True)
        try:
            thread = await ch.create_thread(
                name=f"support-{interaction.user.name}-{interaction.user.id}",
                type=discord.ChannelType.private_thread,
            )
            await thread.add_user(interaction.user)
            emb = discord.Embed(title="New Support Request", color=0x2b88d8)
            emb.add_field(name="User", value=interaction.user.mention, inline=True)
            emb.add_field(name="Subject", value=str(self.subject), inline=True)
            emb.add_field(name="Details", value=str(self.details), inline=False)
            await thread.send(_admin_mentions(), embed=emb)
            await interaction.followup.send(f"Created {thread.mention}", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("I need **Manage Threads** permission here.", ephemeral=True)

# ------------------------------- View --------------------------------

class PortalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Whitelist", style=discord.ButtonStyle.primary, custom_id="portal:whitelist")
    async def whitelist_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _has_any_role(interaction.user, WHITELIST_ALLOWED_ROLE_IDS):
            return await interaction.response.send_message("You don’t have permission to request whitelist.", ephemeral=True)
        await interaction.response.send_modal(WhitelistModal())

    @discord.ui.button(label="Server Info", style=discord.ButtonStyle.secondary, custom_id="portal:status")
    async def status_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await _ack(interaction)
        try:
            info = await asyncio.wait_for(get_status(), timeout=8)
            await interaction.followup.send(embed=_portal_embed(server_info=info), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Status error: `{e}`", ephemeral=True)

    @discord.ui.button(label="Server Properties", style=discord.ButtonStyle.secondary, custom_id="portal:props")
    async def props_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await _ack(interaction)
        try:
            text = await asyncio.wait_for(read_server_properties_text(), timeout=10)
            d: dict[str, str] = {}
            for line in text.splitlines():
                if line.strip() and not line.strip().startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    d[k.strip()] = v.strip()
            keys = ("motd", "difficulty", "max-players", "online-mode", "server-port", "pvp", "view-distance")
            subset = {k: d[k] for k in keys if k in d}
            snippet = "\n".join(f"{k}={v}" for k, v in list(d.items())[:12])
            emb = _portal_embed(props_small=subset)
            if snippet:
                emb.add_field(name="Snippet", value=f"```properties\n{snippet}\n```", inline=False)
            await interaction.followup.send(embed=emb, ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("SFTP error: timed out.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"SFTP error: `{e}`", ephemeral=True)

    @discord.ui.button(label="Ask Admin", style=discord.ButtonStyle.success, custom_id="portal:support")
    async def support_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(SupportModal())

    @discord.ui.button(label="Copy Connect", style=discord.ButtonStyle.secondary, custom_id="portal:copyconnect")
    async def copy_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        # Discord can't copy to clipboard directly; send an ephemeral message easy to copy.
        await _ack(interaction)
        txt = f"{SRV_DNS}:{SRV_PORT}\n{SRV_IP}:{SRV_PORT}"
        await interaction.followup.send(
            f"Copy one of these and paste into Minecraft:\n```text\n{txt}\n```",
            ephemeral=True
        )

    @discord.ui.button(label="Plugins", style=discord.ButtonStyle.secondary, custom_id="portal:plugins")
    async def plugins_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await _ack(interaction)
        try:
            names = await asyncio.wait_for(list_plugins(), timeout=12)
            # Keep only directories (list_plugins marks dirs with trailing '/')
            folders = [n[:-1] for n in names if n.endswith("/")]
            if not folders:
                return await interaction.followup.send("No plugin folders found in `MC_PLUGINS_DIR`.", ephemeral=True)

            # Nicely formatted, cap long lists
            shown = folders[:50]
            more = len(folders) - len(shown)
            block = "\n".join(shown)
            desc = f"Found **{len(folders)}** plugin folder(s):\n```text\n{block}\n```"
            if more > 0:
                desc += f"\n… and **{more} more**"
            e = discord.Embed(title="📦 Plugins (folders)", description=desc, color=0x2b88d8)
            e.set_footer(text="From MC_PLUGINS_DIR via SFTP")
            await interaction.followup.send(embed=e, ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("SFTP error: timed out while listing plugins.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"SFTP error while listing plugins: `{e}`", ephemeral=True)

# ------------------------------- Cog ---------------------------------

class PortalCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(PortalView())
        await self._post_or_update_portal()

    async def _post_or_update_portal(self):
        ch = self.bot.get_channel(PORTAL_CHANNEL_ID)
        if not isinstance(ch, discord.TextChannel):
            log.error("[portal] Channel %s not found or wrong type.", PORTAL_CHANNEL_ID)
            return

        info, props_small = None, None
        with contextlib.suppress(Exception):
            info = await asyncio.wait_for(get_status(), timeout=8)
        with contextlib.suppress(Exception):
            text = await asyncio.wait_for(read_server_properties_text(), timeout=10)
            d = {}
            for line in text.splitlines():
                if line.strip() and not line.strip().startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    d[k.strip()] = v.strip()
            keys = ("motd", "difficulty", "max-players", "server-port")
            props_small = {k: d[k] for k in keys if k in d}

        embed = _portal_embed(server_info=info, props_small=props_small)

        # try to find existing portal to edit
        existing = None
        async for m in ch.history(limit=50):
            if m.author == self.bot.user and m.embeds and (m.embeds[0].footer and m.embeds[0].footer.text == "GameOperator Portal"):
                existing = m
                break

        try:
            if existing:
                await existing.edit(embed=embed, view=PortalView())
                log.info("[portal] Updated portal message: %s", existing.id)
            else:
                msg = await ch.send(embed=embed, view=PortalView())
                log.info("[portal] Posted portal message: %s", msg.id)
        except Exception:
            log.exception("[portal] Failed to post/update portal message.")

    @app_commands.command(name="portal", description="Repost the portal here")
    async def portal(self, interaction: discord.Interaction):
        await _ack(interaction)
        await self._post_or_update_portal()
        await interaction.followup.send("Portal posted/updated.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(PortalCog(bot))
