"""外部配置参数：一律通过环境变量读取，可被 .env 覆盖。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """后端运行配置。

    环境变量优先级高于 .env 文件；变量名不区分大小写。
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False


settings = Settings()
