"""LM Studio lmstudio-community GGUF 모델 프로필."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LlmModelProfile:
    id: str
    model_id: str
    ram_gb: float
    quant: str
    label: str
    description: str
    lms_get: str
    korean: str
    json: str
    daemon: str


# LLM 할당 ~8GB 기준 (가중치 + KV).
PROFILES: dict[str, LlmModelProfile] = {
    "r1": LlmModelProfile(
        id="r1",
        model_id="lmstudio-community/DeepSeek-R1-0528-Qwen3-8B-GGUF",
        ram_gb=5.0,
        quant="Q4_K_M (~5GB) · Q8_0 (~8.7GB)",
        label="추론 (DeepSeek R1)",
        description="DeepSeek-R1 distilled Qwen3 8B. 기술 뉴스 분석·추론 강함. reasoning 블록 자동 제거.",
        lms_get="lmstudio-community/DeepSeek-R1-0528-Qwen3-8B-GGUF",
        korean="good",
        json="good",
        daemon="good",
    ),
    "korean": LlmModelProfile(
        id="korean",
        model_id="unsloth/Qwen3-8B-GGUF",
        ram_gb=5.0,
        quant="Q4_K_M (~5GB) · UD-Q4_K_XL (~5.1GB) · Q8_0 (~8.7GB)",
        label="한국어 우선 (권장)",
        description="Unsloth Dynamic 2.0 Qwen3 8B. GeekNews 한국어 요약·JSON 최적.",
        lms_get="unsloth/Qwen3-8B-GGUF",
        korean="excellent",
        json="good",
        daemon="excellent",
    ),
    "balanced": LlmModelProfile(
        id="balanced",
        model_id="lmstudio-community/gemma-3-12b-it-GGUF",
        ram_gb=7.3,
        quant="Q4_K_M (~7.3GB)",
        label="균형",
        description="Gemma 3 12B. JSON·인스트럭션 준수 우수. 텍스트 전용 GGUF 파일 선택.",
        lms_get="lmstudio-community/gemma-3-12b-it-GGUF",
        korean="good",
        json="good",
        daemon="good",
    ),
    "legacy": LlmModelProfile(
        id="legacy",
        model_id="lmstudio-community/Qwen2.5-7B-Instruct-GGUF",
        ram_gb=8.1,
        quant="Q8_0 (~8.1GB)",
        label="검증된 7B",
        description="Qwen2.5 7B Instruct. 안정적 한국어·JSON. 8GB 꽉 채울 때 Q8.",
        lms_get="lmstudio-community/Qwen2.5-7B-Instruct-GGUF",
        korean="excellent",
        json="good",
        daemon="excellent",
    ),
    "fast": LlmModelProfile(
        id="fast",
        model_id="lmstudio-community/Qwen3-4B-GGUF",
        ram_gb=2.5,
        quant="Q4_K_M (~2.5GB)",
        label="고속·경량",
        description="Qwen3 4B. 백로그 대량 처리·테스트용.",
        lms_get="lmstudio-community/Qwen3-4B-GGUF",
        korean="good",
        json="fair",
        daemon="excellent",
    ),
}

DEFAULT_PROFILE = "korean"
TARGET_RAM_GB = 8
PROVIDER = "lmstudio"


def resolve_llm_model(
    *,
    profile: str | None = None,
    model_override: str | None = None,
) -> tuple[str, LlmModelProfile | None]:
    """LLM_MODEL(직접 지정) > LLM_PROFILE 순으로 API model ID 결정."""
    if model_override and model_override.strip():
        return model_override.strip(), None

    key = (profile or DEFAULT_PROFILE).strip().lower()
    # 구 프로필 호환
    aliases = {"quality": "korean", "nemotron": "korean"}
    key = aliases.get(key, key)

    if key not in PROFILES:
        known = ", ".join(sorted(PROFILES))
        raise ValueError(f"알 수 없는 LLM_PROFILE={profile!r}. 사용 가능: {known}")

    p = PROFILES[key]
    return p.model_id, p


def format_profiles_table(*, ram_gb: float = TARGET_RAM_GB) -> str:
    lines = [
        f"LM Studio · lmstudio-community GGUF (LLM 할당 ~{int(ram_gb)}GB)",
        f"  LLM_PROFILE=<id> 로 선택 (LLM_MODEL 이 있으면 프로필 무시)",
        f"  다운로드: lms get <repo> --gguf -y",
        "",
    ]
    for p in PROFILES.values():
        fit = "✓" if p.ram_gb <= ram_gb else "△ Q8 등 고양자 주의"
        lines.append(f"  {p.id:<10} {fit}  {p.quant}  {p.label}")
        lines.append(f"             API model: {p.model_id}")
        lines.append(f"             lms get:   {p.lms_get}")
        lines.append(f"             {p.description}")
        lines.append(
            f"             한국어:{p.korean}  JSON:{p.json}  데몬:{p.daemon}"
        )
        lines.append("")
    lines.append(f"기본값: LLM_PROFILE={DEFAULT_PROFILE}")
    lines.append("서버: ./scripts/start-lmstudio-server.sh  (포트 1234)")
    return "\n".join(lines)
