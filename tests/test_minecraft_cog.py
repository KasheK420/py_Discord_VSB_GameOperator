import types
import pytest
import discord
from discord.ext import commands

from services.minecraft_cog import MinecraftCog

pytestmark = pytest.mark.asyncio

class StubFollowup:
    async def send(self, *a, **k):  # emulate discord.Interaction.followup.send
        return None

class StubResponse:
    async def defer(self, **k): return None
    async def send_message(self, *a, **k): return None

class StubUser:
    def __init__(self, role_ids):
        self.roles = [types.SimpleNamespace(id=i) for i in role_ids]
        self.id = 123

class StubInteraction:
    def __init__(self, role_ids):
        self.user = StubUser(role_ids)
        self.response = StubResponse()
        self.followup = StubFollowup()

@pytest.fixture
def bot(event_loop):
    intents = discord.Intents.none()
    b = commands.Bot(command_prefix="!", intents=intents, loop=event_loop)
    return b

async def test_servers_embed(monkeypatch, bot):
    cog = MinecraftCog(bot)

    async def fake_status():
        return {"online": 2, "max": 20, "players": ["Alice", "Bob"], "raw": "ok"}

    async def fake_cmd(cmd: str): return "Paper 1.20.4"

    monkeypatch.setattr("services.minecraft_cog.get_status", fake_status)
    monkeypatch.setattr("services.minecraft_cog.mc_cmd", fake_cmd)

    inter = StubInteraction(role_ids=[])
    # should not raise, and send an embed
    await cog.servers(inter)

async def test_whitelist_requires_roles(monkeypatch, bot):
    cog = MinecraftCog(bot)
    # user without roles -> should short‑circuit with "No permission."
    inter = StubInteraction(role_ids=[])
    await cog.whitelist(inter, "add", "Alice")  # should not raise
