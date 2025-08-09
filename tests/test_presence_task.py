
"""
    The above code defines a test function that sets up a fake status and tests the presence updates in
    a Discord bot using asyncio.
    
    @param monkeypatch The `monkeypatch` fixture in pytest allows you to modify attributes, environment
    variables, or any other part of your code for the duration of a test. It is commonly used for
    mocking or patching objects and functions during testing to isolate the code being tested.
"""

import asyncio

import types
import pytest
import discord
from services.presence_task import setup_presence_tasks

pytestmark = pytest.mark.asyncio

class StubVoice:
    def __init__(self, name="old"): self.name = name
    async def edit(self, name): self.name = name

class StubBot:
    def __init__(self):
        self._closed = False
        self.loop = asyncio.get_event_loop()
        self._channel = StubVoice()
    async def wait_until_ready(self): return
    def is_closed(self): return self._closed
    def get_channel(self, _id): return self._channel
    async def change_presence(self, **_): return None

async def test_presence_updates(monkeypatch):
    async def fake_status():
        return {"online": 3, "max": 10, "players": [], "raw": ""}

    monkeypatch.setattr("services.presence_task.get_status", fake_status)

    bot = StubBot()
    setup_presence_tasks(bot)
    # give the loop a tick
    await asyncio.sleep(0.05)
    # stop further loops
    bot._closed = True
