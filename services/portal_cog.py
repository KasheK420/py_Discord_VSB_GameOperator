# services/portal_cog.py
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands

# --- deps from requirements.txt ---
# aio-mc-rcon==3.4.1, asyncssh==2.16.0
from aiomcrcon import Client as RconClient
import asyncssh

log = logging.getLogger(__name__)

# ---------- ENV helpers ----------
def _getenv(key: str, default: str = "") -> str:
    # prefer utils.config.settings if present, fallback to env
    try:
        from utils.config import settings  # type: ignore
        return str(getattr(settings, key))
    except Exception:
        return os.getenv(key, default)

def _csv_ids(val: str) -> list[int]:
    return [int(x.strip()) for x in val.split(",") if x.strip().isdigit()]

PORTAL_CHANNEL_ID = int(_getenv("PORTAL_CHANNEL_ID", "1404017766922715226"))

# Roles that CAN use the Whitelist modal (if empty -> everyone)
WHITELIST_ALLOWED_ROLE_IDS = _csv_ids(_getenv("DISCORD_WHITELIST_ALLOWED_ROLE_IDS", ""))

# Roles to tag in support thread
ADMIN_ROLE_IDS = _csv_ids(_getenv("DISCORD_ADMIN_ROLE_IDS", "")) + _csv_ids(_getenv("DISCORD_MOD_ROLE_IDS", ""))

# RCON
RCON_HOST = _getenv("MC_RCON_HOST")
RCON_PORT = int(_getenv("MC_RCON_PORT", "25575") or 25575)
RCON_PASSWORD = _getenv("MC_RCON_PASSWORD")

# SFTP
SFTP_HOST = _getenv("MC_SFTP_HOST")
SFTP_PORT = int(_getenv("MC_SFTP_PORT", "22") or 22)
SFTP_USER = _getenv("MC_SFTP_USER")
SFTP_PASSWORD = _getenv("MC_SFTP_PASSWORD")  # or use key auth if you prefer
MC_PROPERTIES_PATH = _getenv("MC_PROPERTIES_PATH", "/home/container/server.properties")

# ---------- RCON / SFTP helpers ----------
async def rcon_cmd(cmd: str, timeout: float = 5.0) -> str:
    async def _run():
        async with RconClient(RCON_HOST, RCON_PORT, RCON_PASSWORD) as cli:
            return await cli.send(cmd)
    return await asyncio.wait_for(_run(), timeout=timeout)

async def get_server_info() -> dict:
    # Fallback-safe parsing from standard RCON commands
    info = {"online": "?", "max": "?", "players": []}
    try:
        raw = await rcon_cmd("list")              # "There are X of a max of Y players online: name1, name2"
        ver = await rcon_cmd("version")           # server version string
        info["version"] = ver.strip()
        # parse list
        # tolerant parse:
        parts = raw.split(":")
        head = parts[0] if parts else raw
        tail = parts[1] if len(parts) > 1 else ""
        # X/Y
        nums = [int(s) for s in head.split() if s.isdigit()]
        if len(nums) >= 2:
            info["online"], info["max"] = nums[0], nums[1]
        # players
        players = [p.strip() for p in tail.split(",") if p.strip()]
        info["players"] = players
    except Exception as e:
        info["error"] = str(e)
    return info

async def fetch_properties() -> dict:
    props: dict[str, str] = {}
    async with asyncssh.connect(
        SFTP_HOST, port=SFTP_PORT, username=SFTP_USER, password=SFTP_PASSWORD,
        known_hosts=None
    ) as conn:
        async with conn.start_sftp_client() as sftp:
            async with sftp.open(MC_PROPERTIES_PATH, "r") as f:
                content = await f.read()
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            props[k.strip()] = v.strip()
    return props

def _admin_mentions() -> str:
    return " ".join(f"<@&{rid}>" for rid in ADMIN_ROLE_IDS) or "@here"

def _has_any_role(user: discord.abc.User | discord.Member, role_ids: list[int]) -> bool:
    if not role_ids or not isinstance(user, discord.Member):
        return True if not role_ids else False
    u = {r.id for r in user.roles}
    return any(rid in u for rid in role_ids)

# ---------- UI ----------
def _portal_embed(server_info: Optional[dict] = None, props: Optional[dict] = None) -> discord.Embed:
    e = discord.Embed(
        title="🎮 Minecraft Server",
        description="Use the buttons below.",
        color=0x5865F2,
    )
    if server_info:
        players = ", ".join(server_info.get("players") or []) or "—"
        e.add_field(name="Online", value=f"{server_info.get('online','?')}/{server_info.get('max','?')}", inline=True)
        e.add_field(name="Players", value=players, inline=True)
        if "version" in server_info:
            e.add_field(name="Version", value=server_info["version"], inline=True)
        if "error" in server_info:
            e.add_field(name="Status Error", value=f"`{server_info['error']}`", inline=False)
    if props:
        show = {k: props.get(k) for k in ("motd","difficulty","max-players","online-mode","server-port") if k in props}
        if show:
            pretty = "\n".join(f"**{k}**: {v}" for k, v in show.items())
            e.add_field(name="Properties (key fields)", value=pretty, inline=False)
    e.set_footer(text="GameOperator Portal")
    return e

class WhitelistModal(discord.ui.Modal, title="Whitelist Request"):
    ign = discord.ui.TextInput(label="Minecraft username", max_length=32)
    note = discord.ui.TextInput(label="Notes (optional)", style=discord.TextStyle.paragraph, required=False)

    def __init__(self):
        super().__init__()

    async def on_submit(self, interaction: discord.Interaction):
        # guard: role check
        if not _has_any_role(interaction.user, WHITELIST_ALLOWED_ROLE_IDS):
            return await interaction.response.send_message("You don’t have permission to request whitelist.", ephemeral=True)

        player = str(self.ign).strip()
        try:
            # Add to whitelist and reload
            await rcon_cmd(f"whitelist add {player}")
            await rcon_cmd("whitelist reload")
            await interaction.response.send_message(f"✅ Added **{player}** to whitelist.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ RCON error: `{e}`", ephemeral=True)

class SupportModal(discord.ui.Modal, title="Contact Admin"):
    subject = discord.ui.TextInput(label="Subject", max_length=80)
    details = discord.ui.TextInput(label="What do you need?", style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self):
        super().__init__()

    async def on_submit(self, interaction: discord.Interaction):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("Run in a text channel.", ephemeral=True)

        try:
            thread = await channel.create_thread(
                name=f"support-{interaction.user.name}-{interaction.user.id}",
                type=discord.ChannelType.private_thread
            )
            await thread.add_user(interaction.user)

            emb = discord.Embed(title="New Support Request", color=0x2b88d8)
            emb.add_field(name="User", value=interaction.user.mention, inline=True)
            emb.add_field(name="Subject", value=str(self.subject), inline=True)
            emb.add_field(name="Details", value=str(self.details), inline=False)
            await thread.send(f"{_admin_mentions()}",
                              embed=emb,
                              silent=False)
            await interaction.response.send_message(f"Created {thread.mention}", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I need **Manage Threads** permission.", ephemeral=True)

class PortalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # persistent

    @discord.ui.button(label="Whitelist", style=discord.ButtonStyle.primary, custom_id="portal:whitelist")
    async def whitelist_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        # check perms before modal
        if not _has_any_role(interaction.user, WHITELIST_ALLOWED_ROLE_IDS):
            return await interaction.response.send_message("You don’t have permission to request whitelist.", ephemeral=True)
        await interaction.response.send_modal(WhitelistModal())

    @discord.ui.button(label="Server Info", style=discord.ButtonStyle.secondary, custom_id="portal:status")
    async def status_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        try:
            info = await get_server_info()
            await interaction.response.send_message(embed=_portal_embed(server_info=info), ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Status error: `{e}`", ephemeral=True)

    @discord.ui.button(label="Server Properties", style=discord.ButtonStyle.secondary, custom_id="portal:props")
    async def props_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        try:
            props = await fetch_properties()
            # show first 10 important lines + count
            keys = ("motd","difficulty","max-players","online-mode","server-port","pvp","view-distance")
            subset = {k: props[k] for k in keys if k in props}
            emb = _portal_embed(props=subset)
            # include a trimmed snippet
            first = list(props.items())[:12]
            snippet = "\n".join(f"{k}={v}" for k, v in first)
            emb.add_field(name="Snippet", value=f"```properties\n{snippet}\n```", inline=False)
            await interaction.response.send_message(embed=emb, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"SFTP error: `{e}`", ephemeral=True)

    @discord.ui.button(label="Ask Admin", style=discord.ButtonStyle.success, custom_id="portal:support")
    async def support_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(SupportModal())

# ---------- Cog ----------
class PortalCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(PortalView())  # persistent handlers
        await self._post_or_update_portal()

    async def _post_or_update_portal(self):
        ch = self.bot.get_channel(PORTAL_CHANNEL_ID)
        if not isinstance(ch, discord.TextChannel):
            log.error("[portal] Channel %s not found or wrong type.", PORTAL_CHANNEL_ID)
            return

        info, props = None, None
        with contextlib.suppress(Exception):
            info = await get_server_info()
        with contextlib.suppress(Exception):
            p = await fetch_properties()
            # only pass a small subset for the top message
            keys = ("motd","difficulty","max-players","server-port")
            props = {k: p[k] for k in keys if k in p}

        embed = _portal_embed(server_info=info, props=props)

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

async def setup(bot: commands.Bot):
    await bot.add_cog(PortalCog(bot))

# small import used above
import contextlib
