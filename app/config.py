from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    papers_per_run: int = 20
    arxiv_categories: str = "cs.AI,cs.LG,cs.CL,cs.CV"
    # Comma/newline-separated seed interests (also loadable via UI or interests file).
    interest_keywords: str = ""
    interests_file: str = "./data/interests.txt"
    # Optional Semantic Scholar API key (higher rate limits).
    semanticscholar_api_key: str = ""
    # When true and interests exist, only keep papers that match at least one keyword.
    require_keyword_match: bool = False
    schedule_day_of_week: str = "mon"
    schedule_hour: int = 9
    schedule_minute: int = 0
    database_url: str = "sqlite:///./data/papers.db"
    app_name: str = "PaperPulse"

    @property
    def categories(self) -> list[str]:
        return [c.strip() for c in self.arxiv_categories.split(",") if c.strip()]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
