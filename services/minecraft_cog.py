# services/minecraft_cog.py
from __future__ import annotations

import textwrap
import discord
from discord.ext import commands
from discord import app_commands

from utils.config import settings
from utils.rcon_client import mc_cmd, get_status
from utils.sftp_client import (
    upload_plugin_from_url,
    edit_server_properties,
)

MAX_MSG = 1900  # keep replies under Discord 2k char cap with code fences

def _is_mod(inter: discord.Interaction) -> bool:
    uid_roles = {r.id for r in getattr(inter.user, "roles", [])}
    allowed = (
        set(settings.roles_from_csv(settings.DISCORD_ADMIN_ROLE_IDS))
        | set(settings.roles_from_csv(settings.DISCORD_MOD_ROLE_IDS))
        | set(settings.roles_from_csv(settings.DISCORD_SERVER_MOD_ROLE_IDS))
    )
    return bool(uid_roles & allowed)

async def _require_mod(inter: discord.Interaction) -> bool:
    if not _is_mod(inter):
        await inter.response.send_message("No permission.", ephemeral=True)
        return False
    return True

async def _reply_ok(inter: discord.Interaction, title: str, body: str, ephemeral: bool = True):
    emb = discord.Embed(title=title, description=f"```text\n{body.strip()[:1800]}\n```", color=0x2ECC71)
    if not inter.response.is_done():
        await inter.response.defer(ephemeral=ephemeral, thinking=True)
    await inter.followup.send(embed=emb, ephemeral=ephemeral)

async def _reply_err(inter: discord.Interaction, title: str, err: Exception | str, ephemeral: bool = True):
    txt = str(err)
    emb = discord.Embed(title=title, description=f"```text\n{txt[:1800]}\n```", color=0xE74C3C)
    if not inter.response.is_done():
        await inter.response.defer(ephemeral=ephemeral, thinking=True)
    await inter.followup.send(embed=emb, ephemeral=ephemeral)

# Attempt Paper-friendly reload first, fall back to vanilla
async def _safe_reload() -> str:
    try:
        out = (await mc_cmd("reload confirm")).strip()
        if "Unknown or incomplete command" in out or "Incorrect argument" in out:
            return (await mc_cmd("reload")).strip()
        return out
    except Exception:
        # Fall back if confirm sub-arg isn’t supported
        return (await mc_cmd("reload")).strip()

class MinecraftCog(commands.Cog):
    """Slash-only admin & utility commands for Minecraft via RCON."""

    # ---- GROUPS -----------------------------------------------------
    player = app_commands.Group(name="player", description="Player management (admin)")
    server = app_commands.Group(name="server", description="Server control (admin)")
    world = app_commands.Group(name="world", description="World/gameplay management (admin)")
    info = app_commands.Group(name="info", description="Server information")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- Minimal /servers (kept; useful as a quick check) ----------
    @app_commands.command(name="servers", description="Show Minecraft server status and version")
    async def servers(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            status = await get_status()
            ver = await mc_cmd("version")
            embed = discord.Embed(title="Minecraft Server", color=discord.Color.green())
            embed.add_field(name="Online", value=f"{status['online']}/{status['max']}", inline=True)
            embed.add_field(name="Players", value=", ".join(status['players']) or "—", inline=True)
            embed.add_field(name="Version", value=str(ver).strip()[:1024], inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await _reply_err(interaction, "Server info error", e)

    # ===================== PLAYER GROUP ==============================

    @player.command(name="op", description="Give operator status to a player")
    @app_commands.describe(player="Minecraft nickname")
    async def player_op(self, interaction: discord.Interaction, player: str):
        if not await _require_mod(interaction): return
        try:
            out = await mc_cmd(f"op {player}")
            await _reply_ok(interaction, "op", out)
        except Exception as e:
            await _reply_err(interaction, "op failed", e)

    @player.command(name="deop", description="Remove operator status from a player")
    @app_commands.describe(player="Minecraft nickname")
    async def player_deop(self, interaction: discord.Interaction, player: str):
        if not await _require_mod(interaction): return
        try:
            out = await mc_cmd(f"deop {player}")
            await _reply_ok(interaction, "deop", out)
        except Exception as e:
            await _reply_err(interaction, "deop failed", e)

    @player.command(name="kick", description="Kick a player")
    @app_commands.describe(player="Minecraft nickname", reason="Optional reason")
    async def player_kick(self, interaction: discord.Interaction, player: str, reason: str | None = None):
        if not await _require_mod(interaction): return
        try:
            cmd = f"kick {player}" + (f" {reason}" if reason else "")
            out = await mc_cmd(cmd)
            await _reply_ok(interaction, "kick", out)
        except Exception as e:
            await _reply_err(interaction, "kick failed", e)

    @player.command(name="ban", description="Ban a player")
    @app_commands.describe(player="Minecraft nickname", reason="Optional reason")
    async def player_ban(self, interaction: discord.Interaction, player: str, reason: str | None = None):
        if not await _require_mod(interaction): return
        try:
            cmd = f"ban {player}" + (f" {reason}" if reason else "")
            out = await mc_cmd(cmd)
            await _reply_ok(interaction, "ban", out)
        except Exception as e:
            await _reply_err(interaction, "ban failed", e)

    @player.command(name="ban_ip", description="Ban an IP address")
    @app_commands.describe(ip="IPv4/IPv6 address")
    async def player_ban_ip(self, interaction: discord.Interaction, ip: str):
        if not await _require_mod(interaction): return
        try:
            out = await mc_cmd(f"ban-ip {ip}")
            await _reply_ok(interaction, "ban-ip", out)
        except Exception as e:
            await _reply_err(interaction, "ban-ip failed", e)

    @player.command(name="pardon", description="Unban a player")
    @app_commands.describe(player="Minecraft nickname")
    async def player_pardon(self, interaction: discord.Interaction, player: str):
        if not await _require_mod(interaction): return
        try:
            out = await mc_cmd(f"pardon {player}")
            await _reply_ok(interaction, "pardon", out)
        except Exception as e:
            await _reply_err(interaction, "pardon failed", e)

    @player.command(name="pardon_ip", description="Unban an IP")
    @app_commands.describe(ip="IPv4/IPv6 address")
    async def player_pardon_ip(self, interaction: discord.Interaction, ip: str):
        if not await _require_mod(interaction): return
        try:
            out = await mc_cmd(f"pardon-ip {ip}")
            await _reply_ok(interaction, "pardon-ip", out)
        except Exception as e:
            await _reply_err(interaction, "pardon-ip failed", e)

    @player.command(name="whitelist", description="Whitelist controls (on/off/add/remove/list)")
    @app_commands.describe(action="on/off/add/remove/list", player="Player for add/remove")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="on", value="on"),
            app_commands.Choice(name="off", value="off"),
            app_commands.Choice(name="add", value="add"),
            app_commands.Choice(name="remove", value="remove"),
            app_commands.Choice(name="list", value="list"),
        ]
    )
    async def player_whitelist(self, interaction: discord.Interaction, action: app_commands.Choice[str], player: str | None = None):
        if not await _require_mod(interaction): return
        try:
            act = action.value
            if act in {"add", "remove"} and not player:
                return await _reply_err(interaction, "whitelist", "Player is required for add/remove.")
            cmd = f"whitelist {act}" + (f" {player}" if player and act in {'add','remove'} else "")
            out = await mc_cmd(cmd)
            await _reply_ok(interaction, "whitelist", out)
        except Exception as e:
            await _reply_err(interaction, "whitelist failed", e)

    # ===================== SERVER GROUP ==============================

    @server.command(name="stop", description="Stop the server")
    async def server_stop(self, interaction: discord.Interaction):
        if not await _require_mod(interaction): return
        try:
            out = await mc_cmd("stop")
            await _reply_ok(interaction, "stop", out)
        except Exception as e:
            await _reply_err(interaction, "stop failed", e)

    @server.command(name="save_all", description="Force save all worlds")
    async def server_save_all(self, interaction: discord.Interaction):
        if not await _require_mod(interaction): return
        try:
            out = await mc_cmd("save-all")
            await _reply_ok(interaction, "save-all", out)
        except Exception as e:
            await _reply_err(interaction, "save-all failed", e)

    @server.command(name="save_off", description="Disable auto-saving (be careful)")
    async def server_save_off(self, interaction: discord.Interaction):
        if not await _require_mod(interaction): return
        try:
            out = await mc_cmd("save-off")
            await _reply_ok(interaction, "save-off", out)
        except Exception as e:
            await _reply_err(interaction, "save-off failed", e)

    @server.command(name="save_on", description="Re-enable auto-saving")
    async def server_save_on(self, interaction: discord.Interaction):
        if not await _require_mod(interaction): return
        try:
            out = await mc_cmd("save-on")
            await _reply_ok(interaction, "save-on", out)
        except Exception as e:
            await _reply_err(interaction, "save-on failed", e)

    @server.command(name="reload", description="Reload datapacks & settings (can lag)")
    async def server_reload(self, interaction: discord.Interaction):
        if not await _require_mod(interaction): return
        try:
            out = await _safe_reload()
            await _reply_ok(interaction, "reload", out)
        except Exception as e:
            await _reply_err(interaction, "reload failed", e)

    @server.command(name="list", description="Show online players")
    async def server_list(self, interaction: discord.Interaction):
        # Allowed for anyone; it’s read-only
        try:
            status = await get_status()
            body = f"Online: {status['online']}/{status['max']}\nPlayers: {', '.join(status['players']) or '—'}"
            await _reply_ok(interaction, "list", body)
        except Exception as e:
            await _reply_err(interaction, "list failed", e)

    # ====================== WORLD GROUP ==============================

    @world.command(name="gamemode", description="Set game mode for a player")
    @app_commands.describe(mode="survival/creative/adventure/spectator", player="Minecraft nickname")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="survival", value="survival"),
            app_commands.Choice(name="creative", value="creative"),
            app_commands.Choice(name="adventure", value="adventure"),
            app_commands.Choice(name="spectator", value="spectator"),
        ]
    )
    async def world_gamemode(self, interaction: discord.Interaction, mode: app_commands.Choice[str], player: str):
        if not await _require_mod(interaction): return
        try:
            out = await mc_cmd(f"gamemode {mode.value} {player}")
            await _reply_ok(interaction, "gamemode", out)
        except Exception as e:
            await _reply_err(interaction, "gamemode failed", e)

    @world.command(name="tp", description="Teleport player(s)")
    @app_commands.describe(target="Player or selector", destination="Player/selector/coords")
    async def world_tp(self, interaction: discord.Interaction, target: str, destination: str):
        if not await _require_mod(interaction): return
        try:
            out = await mc_cmd(f"tp {target} {destination}")
            await _reply_ok(interaction, "tp", out)
        except Exception as e:
            await _reply_err(interaction, "tp failed", e)

    @world.command(name="time_set", description="Set time (day, night, or ticks)")
    @app_commands.describe(value="day/night or numeric ticks")
    async def world_time_set(self, interaction: discord.Interaction, value: str):
        if not await _require_mod(interaction): return
        try:
            out = await mc_cmd(f"time set {value}")
            await _reply_ok(interaction, "time set", out)
        except Exception as e:
            await _reply_err(interaction, "time set failed", e)

    @world.command(name="time_add", description="Add ticks to time")
    @app_commands.describe(ticks="Number of ticks to add")
    async def world_time_add(self, interaction: discord.Interaction, ticks: int):
        if not await _require_mod(interaction): return
        try:
            out = await mc_cmd(f"time add {ticks}")
            await _reply_ok(interaction, "time add", out)
        except Exception as e:
            await _reply_err(interaction, "time add failed", e)

    @world.command(name="weather", description="Set weather")
    @app_commands.describe(kind="clear/rain/thunder")
    @app_commands.choices(
        kind=[
            app_commands.Choice(name="clear", value="clear"),
            app_commands.Choice(name="rain", value="rain"),
            app_commands.Choice(name="thunder", value="thunder"),
        ]
    )
    async def world_weather(self, interaction: discord.Interaction, kind: app_commands.Choice[str]):
        if not await _require_mod(interaction): return
        try:
            out = await mc_cmd(f"weather {kind.value}")
            await _reply_ok(interaction, "weather", out)
        except Exception as e:
            await _reply_err(interaction, "weather failed", e)

    @world.command(name="difficulty", description="Change difficulty")
    @app_commands.describe(level="peaceful/easy/normal/hard")
    @app_commands.choices(
        level=[
            app_commands.Choice(name="peaceful", value="peaceful"),
            app_commands.Choice(name="easy", value="easy"),
            app_commands.Choice(name="normal", value="normal"),
            app_commands.Choice(name="hard", value="hard"),
        ]
    )
    async def world_difficulty(self, interaction: discord.Interaction, level: app_commands.Choice[str]):
        if not await _require_mod(interaction): return
        try:
            out = await mc_cmd(f"difficulty {level.value}")
            await _reply_ok(interaction, "difficulty", out)
        except Exception as e:
            await _reply_err(interaction, "difficulty failed", e)

    @world.command(name="worldborder_set", description="Set world border size")
    @app_commands.describe(size="Border size")
    async def world_worldborder_set(self, interaction: discord.Interaction, size: int):
        if not await _require_mod(interaction): return
        try:
            out = await mc_cmd(f"worldborder set {size}")
            await _reply_ok(interaction, "worldborder set", out)
        except Exception as e:
            await _reply_err(interaction, "worldborder set failed", e)

    @world.command(name="effect_give", description="Give potion effect")
    @app_commands.describe(player="Nickname", effect="Effect id/name", duration="Seconds (optional)", amplifier="Level (optional)")
    async def world_effect_give(self, interaction: discord.Interaction, player: str, effect: str, duration: int | None = None, amplifier: int | None = None):
        if not await _require_mod(interaction): return
        try:
            cmd = f"effect give {player} {effect}"
            if duration is not None: cmd += f" {duration}"
            if amplifier is not None: cmd += f" {amplifier}"
            out = await mc_cmd(cmd)
            await _reply_ok(interaction, "effect give", out)
        except Exception as e:
            await _reply_err(interaction, "effect give failed", e)

    @world.command(name="effect_clear", description="Clear potion effects")
    @app_commands.describe(player="Nickname")
    async def world_effect_clear(self, interaction: discord.Interaction, player: str):
        if not await _require_mod(interaction): return
        try:
            out = await mc_cmd(f"effect clear {player}")
            await _reply_ok(interaction, "effect clear", out)
        except Exception as e:
            await _reply_err(interaction, "effect clear failed", e)

    # ======================= INFO GROUP ==============================

    @info.command(name="seed", description="Show world seed")
    async def info_seed(self, interaction: discord.Interaction):
        try:
            out = await mc_cmd("seed")
            await _reply_ok(interaction, "seed", out)
        except Exception as e:
            await _reply_err(interaction, "seed error", e)

    @info.command(name="datapack_list", description="List datapacks")
    async def info_datapack_list(self, interaction: discord.Interaction):
        try:
            out = await mc_cmd("datapack list")
            await _reply_ok(interaction, "datapack list", out)
        except Exception as e:
            await _reply_err(interaction, "datapack list error", e)

    @info.command(name="scoreboard_objectives_list", description="List scoreboard objectives")
    async def info_scoreboard_objectives_list(self, interaction: discord.Interaction):
        try:
            out = await mc_cmd("scoreboard objectives list")
            await _reply_ok(interaction, "scoreboard objectives list", out)
        except Exception as e:
            await _reply_err(interaction, "scoreboard objectives list error", e)

    # ======================= EDIT PROPERTIES =========================

    @app_commands.command(name="properties", description="Edit server.properties (key=value, key2=value2, …)")
    @app_commands.describe(kv='Comma separated key=value pairs, e.g. "motd=Hello,max-players=50"')
    async def properties_edit(self, interaction: discord.Interaction, kv: str):
        if not _is_mod(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)
        try:
            pairs = {k.strip(): v.strip() for k, v in (item.split("=", 1) for item in kv.split(",") if "=" in item)}
            if not pairs:
                return await interaction.response.send_message("Nothing to change. Provide key=value pairs.", ephemeral=True)
            await interaction.response.defer(thinking=True, ephemeral=True)
            await edit_server_properties(pairs)
            # Do not force full server reload; Paper datapack reload is heavy. Admin can /server reload if needed.
            await interaction.followup.send(f"Updated: `{pairs}`", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error updating properties: `{e}`", ephemeral=True)

    # ======================= INSTALL PLUGIN ==========================

    @app_commands.command(name="plugin", description="Install plugin from a direct URL to a .jar")
    @app_commands.describe(url="Direct URL to plugin .jar")
    async def plugin_install(self, interaction: discord.Interaction, url: str):
        if not _is_mod(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)
        try:
            await interaction.response.defer(thinking=True, ephemeral=True)
            await upload_plugin_from_url(url)
            await interaction.followup.send("Plugin uploaded. Use `/server reload` to load it.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error uploading plugin: `{e}`", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MinecraftCog(bot))
