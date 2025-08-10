from __future__ import annotations

import inspect
import logging
from typing import Iterable, List, Tuple, Union

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)


def _usage_for(cmd: Union[app_commands.Command, app_commands.ContextMenu]) -> str:
    """
    Build a very simple usage string like '/foo <arg1> [arg2]'.
    We introspect the callback signature: (self, interaction, *params).
    """
    if isinstance(cmd, app_commands.ContextMenu):
        return f"/{cmd.name} (context menu)"
    try:
        sig = inspect.signature(cmd.callback)  # type: ignore[attr-defined]
        params = list(sig.parameters.values())

        # strip 'self' and 'interaction'
        if params and params[0].name == "self":
            params = params[1:]
        if params and params[0].name in ("interaction", "inter"):
            params = params[1:]

        parts = []
        for p in params:
            if p.default is inspect._empty:
                parts.append(f"<{p.name}>")
            else:
                parts.append(f"[{p.name}]")
        return f"/{cmd.qualified_name} " + " ".join(parts)
    except Exception:
        return f"/{cmd.qualified_name}"


def _flatten_commands(tree: app_commands.CommandTree) -> List[app_commands.Command]:
    """
    Return a flat list of all top-level commands and subcommands from groups.
    """
    flat: List[app_commands.Command] = []

    def visit(c: Union[app_commands.Command, app_commands.Group]):
        if isinstance(c, app_commands.Group):
            for sub in c.commands:
                visit(sub)
        else:
            flat.append(c)

    for c in tree.get_commands():
        if isinstance(c, (app_commands.Command, app_commands.Group)):
            visit(c)
    # dedupe by qualified_name just in case
    seen = set()
    out = []
    for c in flat:
        if c.qualified_name not in seen:
            out.append(c)
            seen.add(c.qualified_name)
    return sorted(out, key=lambda x: x.qualified_name)


class HelpCog(commands.Cog):
    """Slash help which inspects the app command tree."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        log.info("[help] loaded")

    @app_commands.command(name="help", description="Show all available commands or details about one command.")
    @app_commands.describe(command="Optional: a specific command name (e.g., 'portal' or 'rcon_diag').")
    async def help_cmd(self, interaction: discord.Interaction, command: str | None = None):
        # Defer quickly so we never hit the 3s timeout
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)

        tree = interaction.client.tree  # type: ignore[attr-defined]
        all_cmds = _flatten_commands(tree)

        if command:
            # Try exact match first, then case-insensitive
            target = None
            for c in all_cmds:
                if c.name == command or c.qualified_name == command:
                    target = c
                    break
            if not target:
                for c in all_cmds:
                    if c.name.lower() == command.lower() or c.qualified_name.lower() == command.lower():
                        target = c
                        break

            if not target:
                return await interaction.followup.send(f"Command `{command}` not found.", ephemeral=True)

            usage = _usage_for(target)
            desc = target.description or "—"
            e = discord.Embed(
                title=f"ℹ️ /{target.qualified_name}",
                description=desc,
                color=0x5865F2,
            )
            e.add_field(name="Usage", value=f"```text\n{usage}\n```", inline=False)

            # If the command is part of a group, show siblings
            parts = target.qualified_name.split()
            if len(parts) > 1:
                parent_name = parts[0]
                parent = next((c for c in tree.get_commands() if isinstance(c, app_commands.Group) and c.name == parent_name), None)
                if parent:
                    siblings = [s for s in parent.commands if isinstance(s, app_commands.Command)]
                    if siblings:
                        sib_lines = [f"/{s.qualified_name} — {s.description or '—'}" for s in siblings]
                        e.add_field(name=f"More in `/{parent.name}`", value="\n".join(sib_lines[:10]), inline=False)

            return await interaction.followup.send(embed=e, ephemeral=True)

        # No specific command → list them all
        lines = [f"/{c.qualified_name} — {c.description or '—'}" for c in all_cmds]
        # Chunk if long
        chunks: list[list[str]] = []
        chunk: list[str] = []
        total = 0
        for line in lines:
            total += 1
            chunk.append(line)
            if len(chunk) >= 15:
                chunks.append(chunk)
                chunk = []
        if chunk:
            chunks.append(chunk)

        embeds: list[discord.Embed] = []
        for idx, ch in enumerate(chunks, start=1):
            e = discord.Embed(
                title="🧭 Commands" + (f" ({idx}/{len(chunks)})" if len(chunks) > 1 else ""),
                description="\n".join(ch),
                color=0x2b88d8,
            )
            e.set_footer(text=f"{len(lines)} command(s)")
            embeds.append(e)

        # Send one or multiple embeds
        if len(embeds) == 1:
            await interaction.followup.send(embed=embeds[0], ephemeral=True)
        else:
            # send first, then the rest to avoid hitting size limits
            await interaction.followup.send(embed=embeds[0], ephemeral=True)
            for e in embeds[1:]:
                await interaction.followup.send(embed=e, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
