import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _hm(value: str) -> tuple[int, int]:
    hour, minute = value.split(":")
    return int(hour), int(minute)


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    veo_model: str = os.getenv("VEO_MODEL", "veo-3.1-generate-preview")
    text_model: str = os.getenv("TEXT_MODEL", "gemini-2.5-flash")
    clips_per_video: int = int(os.getenv("CLIPS_PER_VIDEO", "1"))
    video_resolution: str = os.getenv("VIDEO_RESOLUTION", "1080p")

    youtube_client_secret: str = os.getenv("YOUTUBE_CLIENT_SECRET", "client_secret.json")
    youtube_token_file: str = os.getenv("YOUTUBE_TOKEN_FILE", "token.json")
    youtube_privacy: str = os.getenv("YOUTUBE_PRIVACY", "public")
    youtube_category_id: str = os.getenv("YOUTUBE_CATEGORY_ID", "24")

    timezone: str = os.getenv("TIMEZONE", "Europe/Amsterdam")
    generate_time: tuple[int, int] = _hm(os.getenv("GENERATE_TIME", "13:00"))
    upload_time: tuple[int, int] = _hm(os.getenv("UPLOAD_TIME", "16:00"))
    stats_interval_hours: int = int(os.getenv("STATS_INTERVAL_HOURS", "3"))
    evolve_day: str = os.getenv("EVOLVE_DAY", "mon")
    evolve_time: tuple[int, int] = _hm(os.getenv("EVOLVE_TIME", "09:00"))

    data_dir: Path = Path(os.getenv("DATA_DIR", "data"))
    disable_scheduler: bool = os.getenv("DISABLE_SCHEDULER", "0") == "1"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "dashboard.db"

    @property
    def video_dir(self) -> Path:
        return self.data_dir / "videos"


settings = Settings()
