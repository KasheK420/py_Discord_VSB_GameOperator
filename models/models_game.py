from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import BigInteger, Column, Integer, String, Float, select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class AccountLink(Base):
    __tablename__ = "account_links"
    id = Column(Integer, primary_key=True)
    discord_id = Column(BigInteger, index=True, unique=True, nullable=False)
    ign = Column(String(32), nullable=False)

    @staticmethod
    async def upsert(s: AsyncSession, *, discord_id: int, ign: str):
        q = select(AccountLink).where(AccountLink.discord_id == discord_id)
        res = await s.execute(q)
        row = res.scalar_one_or_none()
        if row:
            row.ign = ign
        else:
            row = AccountLink(discord_id=discord_id, ign=ign)
            s.add(row)
        await s.commit()
        return row

    @staticmethod
    async def delete_by_discord(s: AsyncSession, discord_id: int):
        await s.execute(delete(AccountLink).where(AccountLink.discord_id == discord_id))
        await s.commit()

    @staticmethod
    async def fetch_all(s: AsyncSession):
        res = await s.execute(select(AccountLink))
        return list(res.scalars())

class PlayerStats(Base):
    __tablename__ = "player_stats"
    id = Column(Integer, primary_key=True)
    player = Column(String(32), index=True, unique=True)
    kills = Column(Integer, default=0)
    deaths = Column(Integer, default=0)
    playtime_hours = Column(Float, default=0.0)

    @staticmethod
    async def upsert(s: AsyncSession, d: dict):
        name = d.get("player")
        q = select(PlayerStats).where(PlayerStats.player == name)
        res = await s.execute(q)
        row = res.scalar_one_or_none()
        if row:
            row.kills = int(d.get("kills", row.kills))
            row.deaths = int(d.get("deaths", row.deaths))
            row.playtime_hours = float(d.get("playtime_hours", row.playtime_hours))
        else:
            row = PlayerStats(player=name, kills=int(d.get("kills",0)), deaths=int(d.get("deaths",0)), playtime_hours=float(d.get("playtime_hours",0)))
            s.add(row)
        await s.commit()
        return row

    @staticmethod
    async def fetch_one(s: AsyncSession, player: str) -> Optional["PlayerStats"]:
        res = await s.execute(select(PlayerStats).where(PlayerStats.player == player))
        return res.scalar_one_or_none()

    @staticmethod
    async def top(s: AsyncSession, metric: str, limit: int = 10):
        if metric not in {"kills","deaths","playtime_hours"}:
            metric = "kills"
        res = await s.execute(select(PlayerStats).order_by(getattr(PlayerStats, metric).desc()).limit(limit))
        return list(res.scalars())