import discord
from discord.ext import commands
from utils.config import settings

ADMIN_TRIGGERS = ("!admin", "/admin")

class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # /admin <message>
    @discord.app_commands.command(name="admin", description="Ping admins with a message")
    async def admin(self, interaction: discord.Interaction, message: str):
        await interaction.response.send_message("Thanks! Admins have been notified.", ephemeral=True)
        channel = self.bot.get_channel(settings.DISCORD_ALERT_CHANNEL_ID)
        if channel:
            roles_to_tag = []
            roles_to_tag += [f"<@&{rid}>" for rid in settings.roles_from_csv(settings.DISCORD_ADMIN_ROLE_IDS)]
            roles_to_tag += [f"<@&{rid}>" for rid in settings.roles_from_csv(settings.DISCORD_MOD_ROLE_IDS)]
            await channel.send(f"{' '.join(roles_to_tag)}\n**/admin report:** {message}\nFrom: <@{interaction.user.id}>")

    # Scan messages for !admin
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        content = message.content.strip()
        if any(content.lower().startswith(t) for t in ADMIN_TRIGGERS):
            # forward to alert channel
            channel = self.bot.get_channel(settings.DISCORD_ALERT_CHANNEL_ID)
            if channel:
                roles_to_tag = []
                roles_to_tag += [f"<@&{rid}>" for rid in settings.roles_from_csv(settings.DISCORD_ADMIN_ROLE_IDS)]
                roles_to_tag += [f"<@&{rid}>" for rid in settings.roles_from_csv(settings.DISCORD_MOD_ROLE_IDS)]
                payload = content.split(maxsplit=1)
                msg = payload[1] if len(payload) > 1 else "(no message)"
                await channel.send(f"{' '.join(roles_to_tag)}\n**!admin report:** {msg}\nFrom: <@{message.author.id}>")
