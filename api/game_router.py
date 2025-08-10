from __future__ import annotations
import os
from fastapi import APIRouter, Header, HTTPException
from typing import Literal

from services.alerts_cog import AlertsCog
from db.models_game import PlayerStats
from utils.db import async_session_maker

router = APIRouter(prefix="/game", tags=["game"]) 

async def _require_token(authorization: str | None):
    token = os.getenv("GAME_EVENT_TOKEN")
    if not token or not authorization or not authorization.startswith("Bearer ") or authorization.split(" ",1)[1] != token:
        raise HTTPException(status_code=401, detail="Unauthorized")

@router.post("/alert/{kind}")
async def post_alert(kind: Literal["rare_loot","boss","suspicious"], payload: dict, authorization: str | None = Header(default=None)):
    await _require_token(authorization)
    # Get bot and AlertsCog via app state, or import your global bot reference
    from main import bot  # adjust if your bot lives elsewhere
    cog: AlertsCog | None = bot.get_cog("AlertsCog")  # type: ignore
    if not cog:
        raise HTTPException(status_code=503, detail="Alerts cog not ready")
    await cog.post_alert(kind, payload)
    return {"ok": True}

@router.post("/stats/update")
async def stats_update(item: dict, authorization: str | None = Header(default=None)):
    await _require_token(authorization)
    # item = {player, kills, deaths, playtime_hours}
    async with async_session_maker() as s:
        await PlayerStats.upsert(s, item)
    return {"ok": True}