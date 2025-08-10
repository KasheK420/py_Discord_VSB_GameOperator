# services/minecraft_cog.py
import textwrap
import discord
from discord.ext import commands
from discord import app_commands
from utils.config import settings
from utils.rcon_client import mc_cmd, get_status
from utils.sftp_client import (
    upload_plugin_from_url,
    edit_server_properties,
    read_server_properties_text,   # NEW
    list_plugins,                   # NEW
)

MAX_MSG = 1900  # to stay under Discord 2000-char hard limit with code fences/etc.

def _is_mod(interaction: discord.Interaction) -> bool:
    uid_roles = {r.id for r in getattr(interaction.user, "roles", [])}
    allowed = (
        set(settings.roles_from_csv(settings.DISCORD_ADMIN_ROLE_IDS))
        | set(settings.roles_from_csv(settings.DISCORD_MOD_ROLE_IDS))
        | set(settings.roles_from_csv(settings.DISCORD_SERVER_MOD_ROLE_IDS))
    )
    return bool(uid_roles & allowed)

class MinecraftCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- /servers ----------
    @app_commands.command(name="servers", description="Show Minecraft server info")
    async def servers(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            status = await get_status()
            ver = await mc_cmd("version")
            embed = discord.Embed(title="Minecraft Server", color=discord.Color.green())
            embed.add_field(name="Online", value=f"{status['online']}/{status['max']}", inline=True)
            embed.add_field(name="Players", value=", ".join(status['players']) or "—", inline=True)
            embed.add_field(name="Version", value=str(ver).strip()[:1024], inline=False)
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Error fetching server info: `{e}`", ephemeral=True)

    # ---------- !servers ----------
    @commands.command(name="servers")
    async def servers_legacy(self, ctx: commands.Context):
        try:
            status = await get_status()
            ver = await mc_cmd("version")
            embed = discord.Embed(title="Minecraft Server", color=discord.Color.green())
            embed.add_field(name="Online", value=f"{status['online']}/{status['max']}", inline=True)
            embed.add_field(name="Players", value=", ".join(status['players']) or "—", inline=True)
            embed.add_field(name="Version", value=str(ver).strip()[:1024], inline=False)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Error fetching server info: `{e}`")

    # ---------- /whitelist ----------
    @app_commands.command(name="whitelist", description="Manage whitelist")
    @app_commands.describe(action="add/remove", player="Minecraft nickname")
    async def whitelist(self, interaction: discord.Interaction, action: str, player: str):
        if not _is_mod(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)
        if action not in {"add", "remove"}:
            return await interaction.response.send_message("Action must be add/remove.", ephemeral=True)
        try:
            await interaction.response.defer(thinking=True, ephemeral=True)
            out = await mc_cmd(f"whitelist {action} {player}")
            await mc_cmd("whitelist reload")
            await interaction.followup.send(f"Done: `{str(out).strip()}`", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: `{e}`", ephemeral=True)

    # ---------- !whitelist ----------
    @commands.group(name="whitelist", invoke_without_command=True)
    async def whitelist_group(self, ctx: commands.Context):
        await ctx.reply("Usage: `!whitelist add <player>` or `!whitelist remove <player>`")

    @whitelist_group.command(name="add")
    @commands.has_any_role(*([int(r) for r in settings.DISCORD_ADMIN_ROLE_IDS.split(',') if r] +
                             [int(r) for r in settings.DISCORD_MOD_ROLE_IDS.split(',') if r] +
                             [int(r) for r in settings.DISCORD_SERVER_MOD_ROLE_IDS.split(',') if r]))
    async def wl_add(self, ctx: commands.Context, player: str):
        try:
            out = await mc_cmd(f"whitelist add {player}")
            await mc_cmd("whitelist reload")
            await ctx.reply(f"Done: `{str(out).strip()}`")
        except Exception as e:
            await ctx.reply(f"Error: `{e}`")

    @whitelist_group.command(name="remove")
    @commands.has_any_role(*([int(r) for r in settings.DISCORD_ADMIN_ROLE_IDS.split(',') if r] +
                             [int(r) for r in settings.DISCORD_MOD_ROLE_IDS.split(',') if r] +
                             [int(r) for r in settings.DISCORD_SERVER_MOD_ROLE_IDS.split(',') if r]))
    async def wl_remove(self, ctx: commands.Context, player: str):
        try:
            out = await mc_cmd(f"whitelist remove {player}")
            await mc_cmd("whitelist reload")
            await ctx.reply(f"Done: `{str(out).strip()}`")
        except Exception as e:
            await ctx.reply(f"Error: `{e}`")

    # ---------- /moderate ----------
    @app_commands.command(name="moderate", description="Kick/Ban a player")
    @app_commands.describe(action="kick/ban", player="nickname", reason="optional")
    async def moderate(self, interaction: discord.Interaction, action: str, player: str, reason: str | None = None):
        if not _is_mod(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)
        if action.lower() not in {"kick", "ban"}:
            return await interaction.response.send_message("Action must be kick/ban.", ephemeral=True)
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            cmd = f"{action.lower()} {player}" + (f" {reason}" if reason else "")
            out = await mc_cmd(cmd)
            await interaction.followup.send(f"Done: `{str(out).strip()}`", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: `{e}`", ephemeral=True)

    # ---------- /server ----------
    @app_commands.command(name="server", description="Start/Stop/Restart/Reload server")
    @app_commands.describe(action="start/stop/restart/reload")
    async def server(self, interaction: discord.Interaction, action: str):
        if not _is_mod(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)
        try:
            await interaction.response.defer(thinking=True, ephemeral=True)
            if action.lower() == "reload":
                out = await mc_cmd("reload confirm")
                return await interaction.followup.send(f"Reload: `{str(out).strip()}`", ephemeral=True)
            await interaction.followup.send("Start/stop/restart not implemented; integrate with your host daemon.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: `{e}`", ephemeral=True)

    # ---------- /properties show / edit ----------
    @app_commands.command(name="properties", description="Show or edit server.properties")
    @app_commands.describe(kv='Use "show" to print, or comma separated key=value pairs to edit.')
    async def properties(self, interaction: discord.Interaction, kv: str):
        if not _is_mod(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        # SHOW
        if kv.strip().lower() in {"show", "list", "print"}:
            try:
                text = await read_server_properties_text()
                # trim if huge
                payload = textwrap.dedent(text)
                if len(payload) > MAX_MSG:
                    payload = payload[:MAX_MSG - 30] + "\n…(truncated)"
                return await interaction.response.send_message(f"```properties\n{payload}\n```", ephemeral=True)
            except Exception as e:
                return await interaction.response.send_message(f"Error reading properties: `{e}`", ephemeral=True)

        # EDIT (key=value, key2=value2,…)
        try:
            pairs = {k.strip(): v.strip() for k, v in (item.split("=", 1) for item in kv.split(",") if "=" in item)}
            if not pairs:
                return await interaction.response.send_message("Nothing to change. Provide key=value pairs or use `show`.", ephemeral=True)
            await edit_server_properties(pairs)
            out = await mc_cmd("reload confirm")
            await interaction.response.send_message(f"Updated properties. Reload output: `{str(out).strip()}`", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error updating properties: `{e}`", ephemeral=True)

    # ---------- /plugin show / install ----------
    @app_commands.command(name="plugin", description="Install plugin from URL or show installed plugins")
    @app_commands.describe(arg='Either "show" to list plugins, or a direct URL to a plugin .jar')
    async def plugin(self, interaction: discord.Interaction, arg: str):
        if not _is_mod(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        # SHOW
        if arg.strip().lower() in {"show", "list"}:
            try:
                names = await list_plugins()
                pretty = "\n".join(names) or "(no plugins found)"
                payload = pretty if len(pretty) <= MAX_MSG else pretty[:MAX_MSG - 30] + "\n…(truncated)"
                return await interaction.response.send_message(f"**Plugins in `{settings.MC_PLUGINS_DIR}`**\n```text\n{payload}\n```", ephemeral=True)
            except Exception as e:
                return await interaction.response.send_message(f"Error listing plugins: `{e}`", ephemeral=True)

        # INSTALL
        try:
            await interaction.response.defer(thinking=True, ephemeral=True)
            await upload_plugin_from_url(arg)
            await interaction.followup.send("Plugin uploaded. Use `/server reload` to load it.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error uploading plugin: `{e}`", ephemeral=True)

    # ---------- Legacy: !properties show / edit ----------
    @commands.group(name="properties", invoke_without_command=True)
    async def properties_group(self, ctx: commands.Context, *, kv: str | None = None):
        # Require role via check in each sub (keeps it simple here)
        if kv is None:
            return await ctx.reply("Usage: `!properties show` or `!properties key=value,key2=value2`")

        if kv.strip().lower() in {"show", "list", "print"}:
            try:
                text = await read_server_properties_text()
                payload = text if len(text) <= MAX_MSG else text[:MAX_MSG - 30] + "\n…(truncated)"
                return await ctx.reply(f"```properties\n{payload}\n```")
            except Exception as e:
                return await ctx.reply(f"Error reading properties: `{e}`")

        try:
            pairs = {k.strip(): v.strip() for k, v in (item.split("=", 1) for item in kv.split(",") if "=" in item)}
            if not pairs:
                return await ctx.reply("Nothing to change. Provide key=value pairs or use `show`.")
            await edit_server_properties(pairs)
            out = await mc_cmd("reload confirm")
            await ctx.reply(f"Updated properties. Reload output: `{str(out).strip()}`")
        except Exception as e:
            await ctx.reply(f"Error updating properties: `{e}`")

    # ---------- Legacy: !plugins (list) ----------
    @commands.command(name="plugins")
    async def plugins_legacy(self, ctx: commands.Context):
        try:
            names = await list_plugins()
            pretty = "\n".join(names) or "(no plugins found)"
            payload = pretty if len(pretty) <= MAX_MSG else pretty[:MAX_MSG - 30] + "\n…(truncated)"
            await ctx.reply(f"**Plugins in `{settings.MC_PLUGINS_DIR}`**\n```text\n{payload}\n```")
        except Exception as e:
            await ctx.reply(f"Error listing plugins: `{e}`")
