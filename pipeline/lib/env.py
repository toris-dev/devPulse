import os
from dataclasses import dataclass
from pathlib import Path

from pipeline.lib.llm_models import DEFAULT_PROFILE, PROVIDER, resolve_llm_model


def _strip_inline_comment(value: str) -> str:
    if "#" not in value:
        return value.strip()
    in_quote = False
    for i, ch in enumerate(value):
        if ch in "\"'":
            in_quote = not in_quote
        elif ch == "#" and not in_quote:
            return value[:i].strip()
    return value.strip()


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def load_env(env_path: Path | None = None, *, override: bool = False) -> Path | None:
    """infra/.env 로드. 인라인 주석(#) 지원."""
    if env_path is None:
        root = Path(__file__).resolve().parents[2]
        env_path = root / "infra" / ".env"

    if not env_path.exists():
        return None

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = _strip_quotes(_strip_inline_comment(value))
        if not key:
            continue
        if override:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)

    return env_path


def _env(*keys: str, default: str = "") -> str:
    """신규 LLM_* 키 우선, MLX_LM_* 레거시 키 fallback."""
    for key in keys:
        val = os.getenv(key)
        if val is not None and val.strip():
            return val.strip()
    return default


def get_llm_base_url() -> str:
    load_env()
    return _env("LLM_BASE_URL", "MLX_LM_BASE_URL", default="http://localhost:1234/v1").rstrip("/")


def get_llm_model_id() -> str:
    load_env()
    model_id, _ = resolve_llm_model(
        profile=_env("LLM_PROFILE", "MLX_LM_PROFILE", default=DEFAULT_PROFILE),
        model_override=_env("LLM_MODEL", "MLX_LM_MODEL"),
    )
    return model_id


def get_mlx_model_id() -> str:
    """레거시 alias."""
    return get_llm_model_id()


@dataclass
class DaemonConfig:
    duration_hours: float
    batch_size: int
    idle_poll_sec: int
    backlog_pause_sec: int
    feeds: list[str]
    llm_provider: str
    llm_base_url: str
    llm_model: str
    llm_profile: str

    @property
    def mlx_base_url(self) -> str:
        return self.llm_base_url

    @property
    def mlx_model(self) -> str:
        return self.llm_model


def get_daemon_config() -> DaemonConfig:
    load_env()
    feeds_raw = os.getenv("FEEDS", "all new ask show top")
    profile = _env("LLM_PROFILE", "MLX_LM_PROFILE", default=DEFAULT_PROFILE)
    return DaemonConfig(
        duration_hours=float(os.getenv("DURATION_HOURS", "0")),
        batch_size=int(os.getenv("BATCH_SIZE", os.getenv("LIMIT", "5"))),
        idle_poll_sec=int(os.getenv("IDLE_POLL_SEC", "90")),
        backlog_pause_sec=int(os.getenv("BACKLOG_PAUSE_SEC", "0")),
        feeds=feeds_raw.split(),
        llm_provider=_env("LLM_PROVIDER", default=PROVIDER),
        llm_base_url=get_llm_base_url(),
        llm_model=get_llm_model_id(),
        llm_profile=profile,
    )
