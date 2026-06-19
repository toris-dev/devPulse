from typing import Any

from pipeline.lib.llm import generate_json

SUMMARY_PROMPT = """당신은 개발자 뉴스 에디터입니다. 아래 GeekNews 글을 분석해 JSON만 출력하세요.

제목: {title}
유형: {feed_type}
요약: {summary}

반드시 아래 JSON 형식만 출력:
{{
  "headline": "카드뉴스용 짧은 헤드라인 (20자 이내)",
  "why_important": "왜 중요한가 (1문장)",
  "bullet_points": ["핵심 포인트 1", "핵심 포인트 2", "핵심 포인트 3"],
  "category": "AI Agents|Infrastructure|DevOps|Frontend|Backend|Security|Database|Open Source|Career|Other",
  "difficulty": "Beginner|Intermediate|Advanced",
  "impact_score": 7.5,
  "short_script": "30초 쇼츠용 나레이션 스크립트 (3-4문장, 한국어)"
}}

impact_score는 1.0~10.0 사이 숫자입니다."""


def _clip(text: str, max_len: int) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _fallback_summary(post: dict[str, Any]) -> dict[str, Any]:
    summary = post.get("summary") or post["title"]
    lines = [line.strip().lstrip("- ").strip() for line in summary.split("\n") if line.strip()]
    bullets = [_clip(line, 70) for line in lines[:3]] or [_clip(post["title"], 70)]
    first = _clip(lines[0], 90) if lines else _clip(post["title"], 90)
    return {
        "headline": _clip(post["title"], 28),
        "why_important": first,
        "bullet_points": bullets,
        "category": "Other",
        "difficulty": "Intermediate",
        "impact_score": 5.0,
        "short_script": _clip(summary.replace("\n", " "), 300),
    }


def summarize_post(post: dict[str, Any]) -> dict[str, Any]:
    prompt = SUMMARY_PROMPT.format(
        title=post["title"],
        feed_type=post.get("feed_type", "news"),
        summary=post.get("summary") or post["title"],
    )
    try:
        result = generate_json(
            prompt,
            system="당신은 개발자 뉴스 에디터입니다. 반드시 유효한 JSON만 출력하세요. 다른 텍스트는 포함하지 마세요.",
        )
    except Exception:
        return _fallback_summary(post)

    bullets = [_clip(str(b), 70) for b in (result.get("bullet_points") or [])[:3]]
    return {
        "headline": _clip(result.get("headline", post["title"]), 28),
        "why_important": _clip(result.get("why_important", ""), 90),
        "bullet_points": bullets,
        "category": result.get("category", "Other"),
        "difficulty": result.get("difficulty", "Intermediate"),
        "impact_score": float(result.get("impact_score", 5.0)),
        "short_script": _clip(result.get("short_script", post.get("summary", "")), 300),
    }
