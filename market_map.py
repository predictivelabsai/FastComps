"""Server-rendered, email-safe country → treatment type → treatment map."""

from __future__ import annotations

from collections import OrderedDict
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1200
HEIGHT = 700


def _font(size: int, *, bold: bool = False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = f"/usr/share/fonts/truetype/dejavu/{name}"
    try:
        return ImageFont.truetype(path, size)
    except OSError:  # pragma: no cover - minimal image fallback
        return ImageFont.load_default()


def _wrapped(draw: ImageDraw.ImageDraw, text: str, font, width: int, lines: int = 2) -> list[str]:
    words = str(text or "").split()
    output: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or draw.textbbox((0, 0), candidate, font=font)[2] <= width:
            current = candidate
            continue
        output.append(current)
        current = word
        if len(output) == lines - 1:
            break
    if current and len(output) < lines:
        output.append(current)
    consumed = " ".join(output)
    if len(consumed) < len(str(text or "")) and output:
        output[-1] = output[-1].rstrip(".,;: ") + "…"
    return output


def _price(value) -> str:
    amount = f"{float(value or 0):,.2f}".rstrip("0").rstrip(".")
    return f"€{amount}"


def render_market_map_png(scan: dict) -> bytes:
    """Render the scan hierarchy as a compact PNG with proportional country blocks."""
    image = Image.new("RGB", (WIDTH, HEIGHT), "#f3f7f5")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((18, 18, WIDTH - 18, HEIGHT - 18), radius=22, fill="#ffffff", outline="#d8e5df", width=2)
    draw.text((48, 42), "DAILY COMPARABLE-PRICE MAP", font=_font(18, bold=True), fill="#177357")
    draw.text((48, 72), "Country  ›  treatment type  ›  treatment", font=_font(30, bold=True), fill="#12241f")
    draw.text((48, 113), "Published EUR market prices; comparison ranges use different clinics.", font=_font(16), fill="#65756f")

    countries: OrderedDict[str, list[dict]] = OrderedDict()
    featured_types: OrderedDict[str, list[dict]] = OrderedDict()
    for row in scan.get("featured_prices", []):
        featured_types.setdefault(str(row.get("treatment_type") or "Treatment"), []).append(row)
    map_rows = []
    for treatment_type, items in featured_types.items():
        prices = [float(item.get("price") or 0) for item in items if float(item.get("price") or 0) > 0]
        if not prices:
            continue
        map_rows.append({
            "country_code": scan.get("featured_country") or "LT",
            "treatment_type": treatment_type,
            "treatment": items[0].get("treatment") if len(items) == 1 else f"{len(items)} featured treatments",
            "lowest_price": min(prices), "highest_price": max(prices),
        })
    map_rows.extend(scan.get("signals", []))
    for signal in map_rows:
        countries.setdefault(str(signal.get("country_code") or "EEA"), []).append(signal)
    if not countries:
        draw.text((48, 190), "No comparable cross-clinic price signals are available yet.", font=_font(22), fill="#65756f")
    else:
        rows: list[list[tuple[str, list[dict]]]] = [[], []]
        weights = [0, 0]
        for item in countries.items():
            target = 0 if weights[0] <= weights[1] else 1
            rows[target].append(item)
            weights[target] += len(item[1])
        top, row_height, gap = 160, 240, 16
        for row_index, groups in enumerate(rows):
            if not groups:
                continue
            x = 38
            available = WIDTH - 76 - gap * (len(groups) - 1)
            total_weight = sum(len(items) for _, items in groups)
            for group_index, (country, items) in enumerate(groups):
                remaining = WIDTH - 38 - x
                panel_width = remaining if group_index == len(groups) - 1 else round(available * len(items) / total_weight)
                y = top + row_index * (row_height + gap)
                x2 = x + panel_width
                draw.rounded_rectangle((x, y, x2, y + row_height), radius=12, fill="#edf5f1", outline="#b9d4c9", width=2)
                draw.rounded_rectangle((x, y, x2, y + 38), radius=12, fill="#177357")
                draw.rectangle((x, y + 25, x2, y + 38), fill="#177357")
                draw.text((x + 12, y + 9), f"{country}  ·  {len(items)} price signal{'s' if len(items) != 1 else ''}", font=_font(15, bold=True), fill="#ffffff")
                child_top = y + 46
                child_height = (row_height - 54) / len(items)
                for index, item in enumerate(items):
                    cy = round(child_top + index * child_height)
                    cy2 = round(child_top + (index + 1) * child_height) - 4
                    low, high = float(item.get("lowest_price") or 0), float(item.get("highest_price") or 0)
                    spread = min(1.0, max(0.0, (high - low) / max(high, 1)))
                    fill = (
                        round(218 + (247 - 218) * spread),
                        round(239 + (218 - 239) * spread),
                        round(230 + (183 - 230) * spread),
                    )
                    draw.rounded_rectangle((x + 7, cy, x2 - 7, cy2), radius=7, fill=fill)
                    draw.text((x + 15, cy + 7), str(item.get("treatment_type") or "Treatment"), font=_font(11, bold=True), fill="#176247")
                    treatment_font = _font(14, bold=True)
                    for line_index, line in enumerate(_wrapped(draw, str(item.get("treatment") or "Treatment"), treatment_font, panel_width - 30, 2)):
                        draw.text((x + 15, cy + 26 + line_index * 17), line, font=treatment_font, fill="#12241f")
                    prices = f"{_price(low)}  →  {_price(high)}"
                    draw.text((x + 15, max(cy + 45, cy2 - 22)), prices, font=_font(13, bold=True), fill="#533f24")
                x = x2 + gap

    draw.text((48, HEIGHT - 45), "FastComps · Source-backed clinic market intelligence · Open the dashboard for full market detail", font=_font(14), fill="#65756f")
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
