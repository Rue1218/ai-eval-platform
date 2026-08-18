from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """由环境变量注入的服务端运行配置。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://aieval:aieval_pass@localhost:5432/aieval"
    secret_key: str = "dev-secret-change-me"
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "admin123"
    key_encryption_key: str = ""
    access_token_expire_minutes: int = 720
    ws_ticket_expire_minutes: int = 5
    data_dir: str = "/data"
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        """将逗号分隔的可信前端 Origin 转换为中间件列表。"""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
