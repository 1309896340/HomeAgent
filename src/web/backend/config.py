"""外部配置参数：一律通过环境变量读取，可被 .env 覆盖。

嵌套配置通过 "." 分隔的环境变量名指定：
  LLM.API_KEY   -> settings.llm.api_key
  ASR.BASE_URL  -> settings.asr.base_url
"""

from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class LLMSettings(BaseModel):
    """大模型服务配置（OpenAI 兼容协议，火山引擎 豆包 agent plan）。"""

    api_key: str = ""
    base_url: str = "https://ark.cn-beijing.volces.com/api/plan/v3"
    model: str = "doubao-seed-2.1-lite"


class ASRSettings(BaseModel):
    """语音识别服务配置（OpenAI 兼容协议，本机 qwen3-asr Docker）。"""

    base_url: str = "http://127.0.0.1:12301/v1"


class Settings(BaseSettings):
    """后端运行配置。

    环境变量优先级高于 .env 文件；变量名不区分大小写。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter=".",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False

    llm: LLMSettings = LLMSettings()
    asr: ASRSettings = ASRSettings()

    @property
    def db_dir(self) -> Path:
        """SQLite 与上传图片的持久化目录（db/）。"""
        return PROJECT_ROOT / "db"

    @property
    def audio_input_dir(self) -> Path:
        """语音输入的调试缓存目录（data/audio_input/）。"""
        return PROJECT_ROOT / "data" / "audio_input"

    @property
    def skills_dir(self) -> Path:
        """对话 Agent 的运行时技能目录（skills/agent/）。

        与 skills/dev/（项目开发流程技能，供开发助手使用）隔离，互不干扰。
        """
        return PROJECT_ROOT / "skills" / "agent"


settings = Settings()
