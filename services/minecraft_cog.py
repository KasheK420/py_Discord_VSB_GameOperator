import discord
from discord.ext import commands
from discord import app_commands
from utils.config import settings
from utils.rcon_client import mc_cmd, get_status
from utils.sftp_client import upload_plugin_from_url, edit_server_properties

def _is_mod(interaction: discord.Interaction) -> bool:
    uid_roles = {r.id for r in interaction.user.roles} if hasattr(interaction.user, "roles") else set()
    allowed = set(settings.roles_from_csv(settings.DISCORD_ADMIN_ROLE_IDS)) \
              | set(settings.roles_from_csv(settings.DISCORD_MOD_ROLE_IDS)) \
              | set(settings.roles_from_csv(settings.DISCORD_SERVER_MOD_ROLE_IDS))
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

    # ---------- /properties ----------
    @app_commands.command(name="properties", description="Edit server.properties (key=value ...)")
    async def properties(self, interaction: discord.Interaction, kv: str):
        if not _is_mod(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)
        try:
            pairs = {k.strip(): v.strip() for k, v in (item.split("=", 1) for item in kv.split(",") if "=" in item)}
            await edit_server_properties(pairs)
            out = await mc_cmd("reload confirm")
            await interaction.response.send_message(f"Updated properties. Reload output: `{str(out).strip()}`", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: `{e}`", ephemeral=True)

    # ---------- /plugin ----------
    @app_commands.command(name="plugin", description="Install plugin from URL")
    async def plugin(self, interaction: discord.Interaction, url: str):
        if not _is_mod(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)
        try:
            await interaction.response.defer(thinking=True, ephemeral=True)
            await upload_plugin_from_url(url)
            await interaction.followup.send("Plugin uploaded. Use `/server reload` to load it.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: `{e}`", ephemeral=True)
