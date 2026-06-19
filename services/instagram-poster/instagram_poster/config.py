import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def project_root() -> Path:
  return Path(__file__).resolve().parents[3]


def _load_env() -> None:
  root = project_root()
  for candidate in (
    root / "infra" / ".env.instagram",
    root / "infra" / ".env",
    Path("/app/infra/.env.instagram"),
    Path("/app/infra/.env"),
  ):
    if candidate.exists():
      load_dotenv(candidate, override=False)


_load_env()


def resolve_data_path(raw: str, *, root: Path | None = None) -> Path:
  """상대 경로는 devPulse 프로젝트 루트 기준 (실행 CWD 무관)."""
  base = root or project_root()
  path = Path(raw)
  if path.is_absolute():
    return path
  return (base / path).resolve()


@dataclass(frozen=True)
class Config:
  ig_user_id: str
  access_token: str
  app_id: str
  output_dir: Path
  sns_dir: Path
  state_db: Path
  timezone: str
  post_times: list[str]
  reels_per_day: int
  poll_sec: int
  graph_version: str
  media_public_base_url: str | None
  dry_run: bool


def load_config() -> Config:
  root = project_root()
  times_raw = os.getenv("IG_POST_TIMES", "09:00,14:00,19:00")
  post_times = [t.strip() for t in times_raw.split(",") if t.strip()]

  output_dir = resolve_data_path(os.getenv("IG_OUTPUT_DIR", "output"), root=root)
  sns_raw = os.getenv("IG_SNS_DIR", "").strip()
  sns_dir = resolve_data_path(sns_raw, root=root) if sns_raw else output_dir / "sns"
  state_raw = os.getenv("IG_STATE_DB", "").strip()
  state_db = resolve_data_path(state_raw, root=root) if state_raw else output_dir / "instagram" / "state.db"

  public_base = os.getenv("IG_MEDIA_PUBLIC_BASE_URL", "").strip() or None
  token = os.getenv("IG_ACCESS_TOKEN", "").strip().replace("\n", "").replace(" ", "")

  return Config(
    ig_user_id=os.getenv("IG_USER_ID", "").strip(),
    access_token=token,
    app_id=os.getenv("IG_APP_ID", "").strip(),
    output_dir=output_dir,
    sns_dir=sns_dir,
    state_db=state_db,
    timezone=os.getenv("IG_TIMEZONE", "Asia/Seoul"),
    post_times=post_times,
    reels_per_day=int(os.getenv("IG_REELS_PER_DAY", "3")),
    poll_sec=int(os.getenv("IG_POLL_SEC", "60")),
    graph_version=os.getenv("IG_GRAPH_VERSION", "v21.0"),
    media_public_base_url=public_base,
    dry_run=os.getenv("IG_DRY_RUN", "0") in ("1", "true", "yes"),
  )
