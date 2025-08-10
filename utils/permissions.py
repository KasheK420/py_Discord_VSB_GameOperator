from __future__ import annotations
import discord
from discord.ext import commands

def guild_only():
    async def predicate(ctx: commands.Context):
        if ctx.guild is None:
            raise commands.NoPrivateMessage("This command can't be used in DMs.")
        return True
    return commands.check(predicate)