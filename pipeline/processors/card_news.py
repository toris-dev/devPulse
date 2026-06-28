from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH = 1080
HEIGHT = 1350
CARD_EXT = "jpg"
MARGIN_X = 72
MARGIN_Y = 48
PANEL_INSET = 40
CARD_PAD_X = 28
CARD_PAD_Y = 22
BULLET_INDEX_SIZE = 54
BULLET_INDEX_GAP = 18
BULLET_ITEM_GAP = 14
SECTION_GAP = 28
TEXT_WIDTH_FUDGE = 12
CONTENT_WIDTH = WIDTH - MARGIN_X * 2
BG_COLOR = (11, 14, 22)
ACCENT = (110, 192, 255)
ACCENT_ALT = (164, 232, 223)
TEXT_PRIMARY = (245, 247, 250)
TEXT_SECONDARY = (173, 181, 193)
TEXT_TERTIARY = (124, 134, 149)
PANEL_FILL = (17, 22, 32, 228)
PANEL_SOFT = (20, 26, 38, 200)
PANEL_STROKE = (255, 255, 255, 22)
DIVIDER = (255, 255, 255, 18)
CHARACTER_SAFE_LEFT = 730
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


def _font_line_height(font: ImageFont.ImageFont, *, leading: float = 1.38) -> int:
    ascent, descent = font.getmetrics()
    return max(1, int((ascent + descent) * leading))


def _safe_text_width(max_width: int) -> int:
    return max(1, max_width - TEXT_WIDTH_FUDGE)


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


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _blend(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(_lerp(c1[i], c2[i], t) for i in range(3))


def _draw_gradient(img: Image.Image, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> None:
    px = img.load()
    for y in range(HEIGHT):
        t = y / max(1, HEIGHT - 1)
        row = _blend(top, bottom, t)
        for x in range(WIDTH):
            px[x, y] = (*row, 255)


def _draw_glow(
    img: Image.Image,
    bbox: tuple[int, int, int, int],
    color: tuple[int, int, int, int],
    *,
    blur: int = 60,
) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.ellipse(bbox, fill=color)
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=blur))
    img.alpha_composite(overlay)


def _draw_panel(
    img: Image.Image,
    bbox: tuple[int, int, int, int],
    *,
    radius: int = 36,
    fill: tuple[int, int, int, int] = PANEL_FILL,
    outline: tuple[int, int, int, int] = PANEL_STROKE,
    width: int = 2,
) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle(bbox, radius=radius, fill=fill, outline=outline, width=width)
    img.alpha_composite(overlay)


def _draw_line(
    draw: ImageDraw.ImageDraw,
    *,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    fill: tuple[int, int, int, int] | tuple[int, int, int],
    width: int = 2,
) -> None:
    draw.line((x1, y1, x2, y2), fill=fill, width=width)


def _draw_chip(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    text_fill: tuple[int, int, int],
    outline: tuple[int, int, int, int] | None = None,
    pad_x: int = 22,
    pad_y: int = 14,
    radius: int = 24,
) -> tuple[int, int, int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0] + pad_x * 2
    h = bbox[3] - bbox[1] + pad_y * 2
    shape = (x, y, x + w, y + h)
    draw.rounded_rectangle(shape, radius=radius, fill=fill, outline=outline)
    draw.text((x + pad_x, y + pad_y - bbox[1]), text, font=font, fill=text_fill)
    return shape


def _draw_character(img: Image.Image, *, x: int, y: int) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    d.ellipse((x + 56, y + 308, x + 286, y + 352), fill=(4, 8, 16, 64))

    d.rounded_rectangle((x + 102, y + 142, x + 250, y + 316), radius=48, fill=(232, 239, 248, 255))
    d.rounded_rectangle((x + 118, y + 158, x + 234, y + 246), radius=30, fill=(32, 40, 60, 255))
    d.rounded_rectangle((x + 128, y + 268, x + 172, y + 338), radius=22, fill=(232, 239, 248, 255))
    d.rounded_rectangle((x + 180, y + 268, x + 224, y + 338), radius=22, fill=(232, 239, 248, 255))

    d.rounded_rectangle((x + 68, y + 8, x + 286, y + 182), radius=54, fill=(241, 245, 251, 255))
    d.rounded_rectangle((x + 92, y + 34, x + 262, y + 138), radius=30, fill=(24, 30, 48, 255))

    d.line((x + 176, y - 8, x + 176, y + 12), fill=(175, 220, 255, 180), width=8)
    d.ellipse((x + 158, y - 28, x + 194, y + 8), fill=(*ACCENT, 255))
    d.ellipse((x + 122, y + 66, x + 158, y + 102), fill=(*ACCENT_ALT, 255))
    d.ellipse((x + 194, y + 66, x + 230, y + 102), fill=(*ACCENT, 255))
    d.rounded_rectangle((x + 136, y + 118, x + 218, y + 130), radius=6, fill=(228, 233, 241, 230))

    d.polygon([(x + 52, y + 222), (x + 84, y + 238), (x + 66, y + 266)], fill=(*ACCENT_ALT, 220))
    d.polygon([(x + 304, y + 204), (x + 278, y + 226), (x + 298, y + 248)], fill=(*ACCENT, 220))

    img.alpha_composite(overlay)


def _draw_bullet_card(
    img: Image.Image,
    *,
    x: int,
    y: int,
    w: int,
    title: str,
    font: ImageFont.ImageFont,
    num_font: ImageFont.ImageFont,
    index: int,
) -> int:
    draw = ImageDraw.Draw(img)
    text_x = x + CARD_PAD_X + BULLET_INDEX_SIZE + BULLET_INDEX_GAP
    text_w = _safe_text_width(w - CARD_PAD_X * 2 - BULLET_INDEX_SIZE - BULLET_INDEX_GAP)
    lines = _wrap_text(title, font, text_w, draw, max_lines=2)
    line_height = _font_line_height(font)
    text_block_h = max(BULLET_INDEX_SIZE, len(lines) * line_height)
    body_h = CARD_PAD_Y * 2 + text_block_h

    _draw_panel(img, (x, y, x + w, y + body_h), radius=26, fill=PANEL_SOFT, outline=(255, 255, 255, 18), width=1)
    draw = ImageDraw.Draw(img)

    index_x1 = x + CARD_PAD_X
    index_y1 = y + CARD_PAD_Y + (text_block_h - BULLET_INDEX_SIZE) // 2
    index_x2 = index_x1 + BULLET_INDEX_SIZE
    index_y2 = index_y1 + BULLET_INDEX_SIZE
    draw.rounded_rectangle((index_x1, index_y1, index_x2, index_y2), radius=16, fill=(255, 255, 255, 22))

    idx_text = f"{index:02d}"
    idx_box = draw.textbbox((0, 0), idx_text, font=num_font)
    tx = index_x1 + (BULLET_INDEX_SIZE - (idx_box[2] - idx_box[0])) / 2
    ty = index_y1 + (BULLET_INDEX_SIZE - (idx_box[3] - idx_box[1])) / 2 - idx_box[1]
    draw.text((tx, ty), idx_text, font=num_font, fill=ACCENT)

    text_y = y + CARD_PAD_Y + max(0, (text_block_h - len(lines) * line_height) // 2)
    _draw_lines(
        draw,
        lines,
        x=text_x,
        y=text_y,
        font=font,
        color=TEXT_PRIMARY,
        line_height=line_height,
        max_y=y + body_h - CARD_PAD_Y,
    )
    return y + body_h


def generate_card_jpeg(post: dict[str, Any], summary: dict[str, Any]) -> bytes:
    img = Image.new("RGBA", (WIDTH, HEIGHT), (*BG_COLOR, 255))
    _draw_gradient(img, (13, 17, 25), (18, 23, 32))
    _draw_glow(img, (-120, -120, 420, 360), (110, 192, 255, 34), blur=90)
    _draw_glow(img, (710, 840, 1120, 1260), (164, 232, 223, 28), blur=110)
    draw = ImageDraw.Draw(img)

    font_title = _load_font(60, bold=True)
    font_sub = _load_font(28)
    font_label = _load_font(20, bold=True)
    font_bullet = _load_font(28)
    font_meta = _load_font(22)
    font_brand = _load_font(28, bold=True)
    font_chip = _load_font(20, bold=True)
    font_impact = _load_font(34, bold=True)
    font_index = _load_font(24, bold=True)

    _draw_panel(
        img,
        (PANEL_INSET, PANEL_INSET, WIDTH - PANEL_INSET, HEIGHT - PANEL_INSET),
        radius=42,
        fill=(14, 18, 26, 228),
        outline=PANEL_STROKE,
        width=1,
    )
    draw = ImageDraw.Draw(img)

    header_y = MARGIN_Y + 24
    category = summary.get("category", "Tech")
    badge_text = category
    _draw_chip(
        draw,
        x=MARGIN_X,
        y=header_y,
        text=badge_text,
        font=font_chip,
        fill=(255, 255, 255, 18),
        text_fill=ACCENT,
        outline=(255, 255, 255, 18),
    )

    impact = float(summary.get("impact_score", 0) or 0)
    diff = str(summary.get("difficulty", "Intermediate")).upper()
    right_w = 212
    impact_top = header_y - 8
    _draw_panel(
        img,
        (WIDTH - MARGIN_X - right_w, impact_top, WIDTH - MARGIN_X, impact_top + 94),
        radius=28,
        fill=(255, 255, 255, 10),
        outline=(255, 255, 255, 16),
        width=1,
    )
    draw = ImageDraw.Draw(img)
    impact_pad_x = 24
    draw.text((WIDTH - MARGIN_X - right_w + impact_pad_x, impact_top + 20), "IMPACT", font=font_label, fill=TEXT_TERTIARY)
    draw.text((WIDTH - MARGIN_X - right_w + impact_pad_x, impact_top + 44), f"{impact:.1f}", font=font_impact, fill=TEXT_PRIMARY)
    draw.text((WIDTH - MARGIN_X - right_w + 108, impact_top + 52), diff, font=font_chip, fill=TEXT_SECONDARY)

    divider_y = impact_top + 94 + SECTION_GAP
    _draw_line(draw, x1=MARGIN_X, y1=divider_y, x2=WIDTH - MARGIN_X, y2=divider_y, fill=DIVIDER, width=2)

    text_right = min(CHARACTER_SAFE_LEFT, WIDTH - MARGIN_X - 32)
    text_width = _safe_text_width(text_right - MARGIN_X)
    title_line_height = _font_line_height(font_title, leading=1.28)
    sub_line_height = _font_line_height(font_sub)

    y = divider_y + SECTION_GAP + 8
    headline = summary.get("headline", post["title"])
    headline_lines = _wrap_text(headline, font_title, text_width, draw, max_lines=3)
    y = _draw_lines(
        draw,
        headline_lines,
        x=MARGIN_X,
        y=y,
        font=font_title,
        color=TEXT_PRIMARY,
        line_height=title_line_height,
        max_y=y + title_line_height * len(headline_lines),
    )

    y += SECTION_GAP
    draw.text((MARGIN_X, y), "WHY IT MATTERS", font=font_label, fill=ACCENT)
    y += _font_line_height(font_label) + 10

    why = summary.get("why_important", "")
    why_lines = _wrap_text(why, font_sub, text_width, draw, max_lines=3)
    y = _draw_lines(
        draw,
        why_lines,
        x=MARGIN_X,
        y=y,
        font=font_sub,
        color=TEXT_SECONDARY,
        line_height=sub_line_height,
        max_y=y + sub_line_height * len(why_lines),
    )

    key_divider_y = y + SECTION_GAP
    _draw_line(draw, x1=MARGIN_X, y1=key_divider_y, x2=text_right, y2=key_divider_y, fill=DIVIDER, width=2)

    bullet_y = key_divider_y + SECTION_GAP
    draw.text((MARGIN_X, bullet_y), "KEY POINTS", font=font_label, fill=TEXT_TERTIARY)
    bullet_y += _font_line_height(font_label) + 14
    bullet_w = text_right - MARGIN_X
    for idx, bullet in enumerate(summary.get("bullet_points", [])[:3], start=1):
        bullet_y = _draw_bullet_card(
            img,
            x=MARGIN_X,
            y=bullet_y,
            w=bullet_w,
            title=bullet,
            font=font_bullet,
            num_font=font_index,
            index=idx,
        )
        bullet_y += BULLET_ITEM_GAP

    _draw_character(img, x=744, y=842)
    draw = ImageDraw.Draw(img)
    draw.text((754, 804), "devPulse", font=font_label, fill=ACCENT)
    draw.text((754, 830), "Signal over noise", font=font_meta, fill=TEXT_SECONDARY)

    footer_h = 108
    footer_y = HEIGHT - footer_h - MARGIN_Y
    _draw_line(draw, x1=MARGIN_X, y1=footer_y - 28, x2=WIDTH - MARGIN_X, y2=footer_y - 28, fill=DIVIDER, width=2)
    draw = ImageDraw.Draw(img)
    draw.text((MARGIN_X, footer_y + 8), "devPulse", font=font_brand, fill=TEXT_PRIMARY)
    draw.text((MARGIN_X, footer_y + 48), f"{category}  /  {diff}", font=font_meta, fill=TEXT_SECONDARY)

    source = str(post.get("source") or post.get("url") or "").replace("https://", "").replace("http://", "")
    if source:
        source = _truncate_to_width(source, font_meta, draw, 320)
    else:
        source = "geeknews"
    draw.text((WIDTH - MARGIN_X - 240, footer_y + 8), "source", font=font_meta, fill=TEXT_TERTIARY)
    draw.text((WIDTH - MARGIN_X - 240, footer_y + 48), source, font=font_meta, fill=TEXT_PRIMARY)

    buf = BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=92, optimize=True, progressive=False)
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


def ensure_card_file(
    post: dict[str, Any],
    cards_dir: Path,
    *,
    verbose: bool = False,
) -> Path:
    """카드 파일이 없으면 DB 요약으로 재생성."""
    path = card_path_for_post(cards_dir, post["id"])
    if path.exists():
        return path

    summary = post.get("llm_summary") or {}
    if isinstance(summary, str):
        import json

        summary = json.loads(summary)
    if not summary:
        raise FileNotFoundError(f"카드 없음 & LLM 요약 없음: {post['id']}")

    from pipeline.lib.log import log

    if verbose:
        log(f"  [{post['id']}] 카드 파일 없음 — 요약으로 재생성")
    card_bytes = generate_card_jpeg(post, summary)
    out_path = cards_dir / f"{post['id']}.{CARD_EXT}"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(card_bytes)
    return out_path
