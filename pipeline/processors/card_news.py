from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1080
HEIGHT = 1350
CARD_EXT = "jpg"
MARGIN_X = 60
CONTENT_WIDTH = WIDTH - MARGIN_X * 2
FOOTER_TOP = HEIGHT - 140
BG_COLOR = (15, 17, 23)
ACCENT = (99, 179, 237)
TEXT_PRIMARY = (240, 244, 248)
TEXT_SECONDARY = (160, 174, 192)
BADGE_BG = (30, 41, 59)
ELLIPSIS = "…"

FONT_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
]


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_PATHS:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size, index=0 if bold else 1)
            except OSError:
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
    return ImageFont.load_default()


def _text_width(text: str, font: ImageFont.ImageFont, draw: ImageDraw.ImageDraw) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _truncate_to_width(
    text: str,
    font: ImageFont.ImageFont,
    draw: ImageDraw.ImageDraw,
    max_width: int,
    *,
    ellipsis: str = ELLIPSIS,
) -> str:
    if _text_width(text, font, draw) <= max_width:
        return text
    trimmed = text
    while trimmed and _text_width(trimmed + ellipsis, font, draw) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + ellipsis) if trimmed else ellipsis


def _wrap_text(
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
    *,
    max_lines: int | None = None,
) -> list[str]:
    if not text:
        return []

    lines: list[str] = []
    current = ""

    for char in text:
        if char == "\n":
            if current:
                lines.append(current)
            current = ""
            if max_lines and len(lines) >= max_lines:
                break
            continue

        test = current + char
        if _text_width(test, font, draw) <= max_width:
            current = test
            continue

        if current:
            lines.append(current)
            if max_lines and len(lines) >= max_lines:
                current = ""
                break
        current = char

    if current and (not max_lines or len(lines) < max_lines):
        lines.append(current)

    if max_lines and len(lines) == max_lines:
        overflow = False
        consumed = sum(len(line) for line in lines[:-1])
        last = lines[-1]
        rest = text[consumed + len(last) :]
        if rest.strip():
            overflow = True
        if overflow:
            lines[-1] = _truncate_to_width(lines[-1], font, draw, max_width)

    return lines


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    *,
    x: int,
    y: int,
    font: ImageFont.ImageFont,
    color: tuple[int, int, int],
    line_height: int,
    max_y: int,
) -> int:
    for line in lines:
        if y + line_height > max_y:
            break
        draw.text((x, y), line, font=font, fill=color)
        y += line_height
    return y


def generate_card_jpeg(post: dict[str, Any], summary: dict[str, Any]) -> bytes:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    font_title = _load_font(48, bold=True)
    font_sub = _load_font(30)
    font_label = _load_font(28)
    font_bullet = _load_font(32)
    font_meta = _load_font(24)
    font_brand = _load_font(28, bold=True)

    draw.rectangle([(0, 0), (WIDTH, 8)], fill=ACCENT)

    feed_type = post.get("feed_type", "news").upper()
    category = summary.get("category", "Tech")
    badge_text = f" {feed_type} · {category} "
    badge_font = _load_font(22)
    badge_bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
    badge_w = badge_bbox[2] - badge_bbox[0] + 24
    badge_h = badge_bbox[3] - badge_bbox[1] + 16
    draw.rounded_rectangle([(MARGIN_X, 60), (MARGIN_X + badge_w, 60 + badge_h)], radius=12, fill=BADGE_BG)
    draw.text((MARGIN_X + 12, 68), badge_text, font=badge_font, fill=ACCENT)

    y = 140
    headline = summary.get("headline", post["title"])
    y = _draw_lines(
        draw,
        _wrap_text(headline, font_title, CONTENT_WIDTH, draw, max_lines=3),
        x=MARGIN_X,
        y=y,
        font=font_title,
        color=TEXT_PRIMARY,
        line_height=58,
        max_y=FOOTER_TOP,
    )

    y += 16
    draw.text((MARGIN_X, y), "왜 중요한가?", font=font_label, fill=ACCENT)
    y += 42

    why = summary.get("why_important", "")
    y = _draw_lines(
        draw,
        _wrap_text(why, font_sub, CONTENT_WIDTH, draw, max_lines=2),
        x=MARGIN_X,
        y=y,
        font=font_sub,
        color=TEXT_SECONDARY,
        line_height=40,
        max_y=FOOTER_TOP,
    )

    y += 20
    for bullet in summary.get("bullet_points", [])[:3]:
        if y + 40 > FOOTER_TOP:
            break
        bullet_lines = _wrap_text(f"• {bullet}", font_bullet, CONTENT_WIDTH, draw, max_lines=2)
        y = _draw_lines(
            draw,
            bullet_lines,
            x=MARGIN_X,
            y=y,
            font=font_bullet,
            color=TEXT_PRIMARY,
            line_height=42,
            max_y=FOOTER_TOP,
        )
        y += 6

    impact = summary.get("impact_score", 0)
    difficulty = summary.get("difficulty", "")
    meta = f"Impact {impact:.1f}  ·  {difficulty}"
    draw.text((MARGIN_X, HEIGHT - 120), meta, font=font_meta, fill=TEXT_SECONDARY)
    draw.text((MARGIN_X, HEIGHT - 80), "devPulse", font=font_brand, fill=ACCENT)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=92, optimize=True, progressive=False)
    return buf.getvalue()


def generate_card_png(post: dict[str, Any], summary: dict[str, Any]) -> bytes:
    """하위 호환 alias."""
    return generate_card_jpeg(post, summary)


def card_path_for_post(cards_dir: Path, post_id: str) -> Path:
    """카드 파일 경로 (.jpg 우선, 레거시 .png fallback)."""
    jpg = cards_dir / f"{post_id}.jpg"
    if jpg.exists():
        return jpg
    png = cards_dir / f"{post_id}.png"
    if png.exists():
        return png
    return jpg
