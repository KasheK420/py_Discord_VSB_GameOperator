from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Discord
    DISCORD_TOKEN: str
    DISCORD_GUILD_ID: int
    DISCORD_ADMIN_ROLE_IDS: str = ""
    DISCORD_MOD_ROLE_IDS: str = ""
    DISCORD_SERVER_MOD_ROLE_IDS: str = ""
    DISCORD_ALERT_CHANNEL_ID: int
    DISCORD_VOICE_CHANNEL_ID: int
    DISCORD_COMMAND_PREFIX: str = "!"

    # RCON
    MC_RCON_HOST: str = "s450618-zn4kp.spot.gs"
    MC_RCON_PORT: int = 31096
    MC_RCON_PASSWORD: str
    MC_SERVER_NAME: str = "VŠB Minecraft"

    # SFTP
    SFTP_HOST: str
    SFTP_PORT: int = 22
    SFTP_USERNAME: str
    SFTP_PASSWORD: str
    MC_SERVER_DIR: str
    MC_PROPERTIES_PATH: str
    MC_PLUGINS_DIR: str
    

    # DB
    DB_HOST: str = "db"
    DB_PORT: int = 5432
    DB_USER: str = "vsb"
    DB_PASSWORD: str = "vsb_password"
    DB_NAME: str = "vsb_bot"

    # App
    APP_ENV: str = "dev"
    LOG_LEVEL: str = "INFO"
    POLL_INTERVAL_SECONDS: int = 15

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    def roles_from_csv(self, csv: str) -> list[int]:
        return [int(x) for x in csv.split(",") if x.strip()]

settings = Settings()
