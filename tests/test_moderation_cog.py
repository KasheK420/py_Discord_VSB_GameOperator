import types
import pytest
import discord
from discord.ext import commands
from services.moderation_cog import ModerationCog

pytestmark = pytest.mark.asyncio

class StubChannel:
    async def send(self, *_a, **_k): return None

class StubMessage:
    def __init__(self, content):
        self.content = content
        self.author = types.SimpleNamespace(bot=False, id=42)

@pytest.fixture
def bot(monkeypatch, event_loop):
    intents = discord.Intents.none()
    b = commands.Bot(command_prefix="!", intents=intents, loop=event_loop)
    c = ModerationCog(b)
    b.get_channel = lambda _id: StubChannel()
    return b

async def test_admin_trigger_forward(bot):
    # use the listener manually
    cog = ModerationCog(bot)
    msg = StubMessage("!admin help me")
    await cog.on_message(msg)  # should not raise
