from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from utils.config import settings

async_engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
async_session_maker = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        yield session
