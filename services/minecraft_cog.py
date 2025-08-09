# services/minecraft_cog.py
import traceback
import discord
from discord.ext import commands
from discord import app_commands

from utils.config import settings
from utils.rcon_client import mc_cmd, get_status
from utils.sftp_client import upload_plugin_from_url, edit_server_properties


def _roles_allowed() -> set[int]:
    return (
        set(settings.roles_from_csv(settings.DISCORD_ADMIN_ROLE_IDS))
        | set(settings.roles_from_csv(settings.DISCORD_MOD_ROLE_IDS))
        | set(settings.roles_from_csv(settings.DISCORD_SERVER_MOD_ROLE_IDS))
    )


def _user_has_allowed_role(user: discord.abc.User | discord.Member | None) -> bool:
    if user and hasattr(user, "roles"):
        uid_roles = {r.id for r in user.roles}  # type: ignore[attr-defined]
        return bool(uid_roles & _roles_allowed())
    return False


class MinecraftCog(commands.Cog):
    """Minecraft controls: status, whitelist, moderation, simple server ops."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------------
    # Status: /servers and !servers
    # -------------------------

    @commands.hybrid_command(name="servers", description="Show Minecraft server status")
    async def servers(self, ctx: commands.Context):
        """
        Works as:
          - Slash: /servers
          - Prefix: !servers
        """
        # For slash calls, avoid 3s timeout
        if getattr(ctx, "interaction", None) and not ctx.interaction.response.is_done():  # type: ignore[attr-defined]
            await ctx.interaction.response.defer(thinking=True)  # type: ignore[attr-defined]

        try:
            status = await get_status()
            embed = discord.Embed(title="Minecraft Server", color=discord.Color.green())
            embed.add_field(name="Online", value=f"{status['online']}/{status['max']}", inline=True)
            embed.add_field(name="Players", value=", ".join(status['players']) or "—", inline=True)
            # version may be long; trim for safety
            ver = (await mc_cmd("version")).strip()
            embed.add_field(name="Version", value=ver[:1024], inline=False)

            if getattr(ctx, "interaction", None):
                await ctx.interaction.followup.send(embed=embed)  # type: ignore[attr-defined]
            else:
                await ctx.reply(embed=embed, mention_author=False)

        except Exception as e:
            msg = (
                "⚠️ Unable to query the server right now.\n"
                f"Reason: `{e.__class__.__name__}`\n"
                "Check MC_RCON_HOST/PORT/password, DNS, and firewall reachability."
            )
            if getattr(ctx, "interaction", None):
                i = ctx.interaction  # type: ignore[attr-defined]
                if not i.response.is_done():
                    await i.response.send_message(msg, ephemeral=True)
                else:
                    await i.followup.send(msg, ephemeral=True)
            else:
                await ctx.reply(msg, mention_author=False)

            # Keep stacktrace in logs
            traceback.print_exc()

    # -------------------------
    # Whitelist: /whitelist and !whitelist ...
    # -------------------------

    @app_commands.command(name="whitelist", description="Manage whitelist (add/remove)")
    @app_commands.describe(action="add or remove", player="Minecraft nickname")
    async def whitelist(self, interaction: discord.Interaction, action: str, player: str):
        if not _user_has_allowed_role(interaction.user):
            return await interaction.response.send_message("⛔ No permission.", ephemeral=True)

        action = (action or "").lower()
        if action not in {"add", "remove"}:
            return await interaction.response.send_message("Usage: action must be `add` or `remove`.", ephemeral=True)

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            out = await mc_cmd(f"whitelist {action} {player}")
            # Some stacks require reload to apply whitelist file changes
            await mc_cmd("whitelist reload")
            await interaction.followup.send(f"✅ Done: `{out.strip()}`", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(
                f"⚠️ Whitelist operation failed: `{e.__class__.__name__}`", ephemeral=True
            )
            traceback.print_exc()

    @commands.group(name="whitelist", invoke_without_command=True)
    async def whitelist_group(self, ctx: commands.Context):
        await ctx.reply("Usage: `!whitelist add <player>` or `!whitelist remove <player>`", mention_author=False)

    def _prefix_perms():
        # Build static role check for prefix commands
        role_ids = (
            [int(r) for r in settings.DISCORD_ADMIN_ROLE_IDS.split(",") if r]
            + [int(r) for r in settings.DISCORD_MOD_ROLE_IDS.split(",") if r]
            + [int(r) for r in settings.DISCORD_SERVER_MOD_ROLE_IDS.split(",") if r]
        )
        return commands.has_any_role(*role_ids)

    @_prefix_perms()
    @whitelist_group.command(name="add")
    async def wl_add(self, ctx: commands.Context, player: str):
        try:
            out = await mc_cmd(f"whitelist add {player}")
            await mc_cmd("whitelist reload")
            await ctx.reply(f"✅ Done: `{out.strip()}`", mention_author=False)
        except Exception as e:
            await ctx.reply(
                f"⚠️ Whitelist add failed: `{e.__class__.__name__}`", mention_author=False
            )
            traceback.print_exc()

    @_prefix_perms()
    @whitelist_group.command(name="remove")
    async def wl_remove(self, ctx: commands.Context, player: str):
        try:
            out = await mc_cmd(f"whitelist remove {player}")
            await mc_cmd("whitelist reload")
            await ctx.reply(f"✅ Done: `{out.strip()}`", mention_author=False)
        except Exception as e:
            await ctx.reply(
                f"⚠️ Whitelist remove failed: `{e.__class__.__name__}`", mention_author=False
            )
            traceback.print_exc()

    # -------------------------
    # Moderate: /moderate
    # -------------------------

    @app_commands.command(name="moderate", description="Kick/Ban a player")
    @app_commands.describe(action="kick or ban", player="nickname", reason="optional reason")
    async def moderate(
        self,
        interaction: discord.Interaction,
        action: str,
        player: str,
        reason: str | None = None,
    ):
        if not _user_has_allowed_role(interaction.user):
            return await interaction.response.send_message("⛔ No permission.", ephemeral=True)

        action = (action or "").lower()
        if action not in {"kick", "ban"}:
            return await interaction.response.send_message("Usage: action must be `kick` or `ban`.", ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            cmd = f"{action} {player}" + (f" {reason}" if reason else "")
            out = await mc_cmd(cmd)
            await interaction.followup.send(f"✅ Done: `{out.strip()}`", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(
                f"⚠️ Moderate failed: `{e.__class__.__name__}`", ephemeral=True
            )
            traceback.print_exc()

    # -------------------------
    # Server lifecycle: /server
    # -------------------------

    @app_commands.command(name="server", description="Start/Stop/Restart/Reload server")
    @app_commands.describe(action="start/stop/restart/reload")
    async def server(self, interaction: discord.Interaction, action: str):
        if not _user_has_allowed_role(interaction.user):
            return await interaction.response.send_message("⛔ No permission.", ephemeral=True)

        action = (action or "").lower()
        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            if action == "reload":
                out = await mc_cmd("reload confirm")  # Paper often requires confirm
                return await interaction.followup.send(f"🔄 Reload: `{out.strip()}`", ephemeral=True)

            # Placeholders for external orchestration
            if action in {"start", "stop", "restart"}:
                return await interaction.followup.send(
                    "🛠️ Start/stop/restart need integration with your host/daemon (SSH/webhook).",
                    ephemeral=True,
                )

            await interaction.followup.send("Usage: action must be start/stop/restart/reload.", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(
                f"⚠️ Server action failed: `{e.__class__.__name__}`", ephemeral=True
            )
            traceback.print_exc()

    # -------------------------
    # Properties: /properties
    # -------------------------

    @app_commands.command(name="properties", description="Edit server.properties (comma-separated key=value)")
    @app_commands.describe(kv='Example: "motd=Hello World,white-list=true"')
    async def properties(self, interaction: discord.Interaction, kv: str):
        if not _user_has_allowed_role(interaction.user):
            return await interaction.response.send_message("⛔ No permission.", ephemeral=True)

        try:
            pairs: dict[str, str] = {}
            for item in (kv or "").split(","):
                if "=" in item:
                    k, v = item.split("=", 1)
                    pairs[k.strip()] = v.strip()

            if not pairs:
                return await interaction.response.send_message(
                    "Provide at least one `key=value`. Example: `motd=Hello World,white-list=true`",
                    ephemeral=True,
                )

            await edit_server_properties(pairs)
            out = await mc_cmd("reload confirm")  # not all props reload; some require restart
            await interaction.response.send_message(
                f"✅ Updated properties. Reload output: `{out.strip()}`", ephemeral=True
            )
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"⚠️ Properties update failed: `{e.__class__.__name__}`", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"⚠️ Properties update failed: `{e.__class__.__name__}`", ephemeral=True
                )
            traceback.print_exc()

    # -------------------------
    # Plugin install: /plugin
    # -------------------------

    @app_commands.command(name="plugin", description="Install a plugin from a direct URL")
    @app_commands.describe(url="Direct link to the .jar (or archive)")
    async def plugin(self, interaction: discord.Interaction, url: str):
        if not _user_has_allowed_role(interaction.user):
            return await interaction.response.send_message("⛔ No permission.", ephemeral=True)

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            await upload_plugin_from_url(url)
            await interaction.followup.send(
                "✅ Plugin uploaded. Use `/server reload` (or restart if required) to load it.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"⚠️ Plugin upload failed: `{e.__class__.__name__}`", ephemeral=True
            )
            traceback.print_exc()
