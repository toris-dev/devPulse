"""레거시 호환 — llm_models 로 위임."""

from pipeline.lib.llm_models import (  # noqa: F401
    DEFAULT_PROFILE,
    PROVIDER,
    PROFILES,
    TARGET_RAM_GB,
    format_profiles_table,
    resolve_llm_model,
)

resolve_mlx_model = resolve_llm_model
