from sqlalchemy import BigInteger, Integer, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base

class Server(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    rcon_host: Mapped[str] = mapped_column(String(255))
    rcon_port: Mapped[int] = mapped_column(Integer)
    sftp_host: Mapped[str] = mapped_column(String(255))
    sftp_port: Mapped[int] = mapped_column(Integer)
    sftp_user: Mapped[str] = mapped_column(String(128))
    # store secrets elsewhere ideally; for demo keep nullable
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class WhitelistEvent(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    player: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(16))  # add/remove
