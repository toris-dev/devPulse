import json
import re

import httpx

from pipeline.lib.env import get_llm_base_url, get_llm_model_id, load_env, _env

_THINK_OPEN = "<" + "think" + ">"
_THINK_CLOSE = "</" + "think" + ">"
_REASONING_OPEN = "<" + "redacted_reasoning" + ">"
_REASONING_CLOSE = "</" + "redacted_reasoning" + ">"


def get_llm_config() -> dict[str, str | float | int]:
    load_env()
    return {
        "base_url": get_llm_base_url(),
        "model": get_llm_model_id(),
        "temperature": float(_env("LLM_TEMPERATURE", "MLX_LM_TEMPERATURE", default="0.3")),
        "max_tokens": int(_env("LLM_MAX_TOKENS", "MLX_LM_MAX_TOKENS", default="1024")),
    }


def generate(
    prompt: str,
    *,
    system: str | None = None,
    timeout: float = 120.0,
) -> str:
    config = get_llm_config()
    model = str(config["model"]).lower()
    user_content = prompt
    # Qwen3 전용 thinking 비활성화 (DeepSeek R1 등 reasoning 모델 제외)
    if (
        "qwen3" in model
        and "deepseek" not in model
        and "r1" not in model
        and "/no_think" not in prompt.lower()
    ):
        user_content = f"{prompt}\n/no_think"

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_content})

    with httpx.Client(timeout=timeout) as client:
        res = client.post(
            f"{config['base_url']}/chat/completions",
            json={
                "model": config["model"],
                "messages": messages,
                "temperature": config["temperature"],
                "max_tokens": config["max_tokens"],
            },
        )
        res.raise_for_status()
        data = res.json()

    choices = data.get("choices") or []
    if not choices:
        raise ValueError(f"Empty LLM response: {data}")

    content = choices[0].get("message", {}).get("content", "")
    return _strip_model_artifacts(content).strip()


def generate_json(
    prompt: str,
    *,
    system: str | None = None,
    timeout: float = 120.0,
) -> dict:
    system_prompt = system or "You are a helpful assistant. Respond with valid JSON only."
    text = generate(prompt, system=system_prompt, timeout=timeout)
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError(f"No JSON found in LLM response: {text[:200]}")
    return json.loads(match.group())


def _strip_model_artifacts(text: str) -> str:
    """Qwen/DeepSeek R1 thinking · reasoning 블록 · 코드펜스 제거."""
    for open_tag, close_tag in (
        (_THINK_OPEN, _THINK_CLOSE),
        (_REASONING_OPEN, _REASONING_CLOSE),
        ("<reasoning>", "</reasoning>"),
    ):
        if close_tag in text:
            text = text.split(close_tag, 1)[-1]
        text = re.sub(
            re.escape(open_tag) + r"[\s\S]*?" + re.escape(close_tag),
            "",
            text,
            flags=re.IGNORECASE,
        )
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        return fenced.group(1).strip()
    return text
