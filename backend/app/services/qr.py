from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

import segno

from app.core.config import settings
from app.core.security import generate_token


@dataclass
class QrPayload:
    svg: str
    png: bytes
    url: str
    filename: str
    size: int = 6
    error_correction: str = "M"
    modules: list[list[bool]] = field(default_factory=list)


def build_menu_url(qr_token: str) -> str:
    """Guest-facing URL encoded in the table QR code."""
    return f"{settings.public_base_url.rstrip('/')}/t/{qr_token}"


def new_table_token() -> str:
    return generate_token(12)


def _inline_svg(qr, *, size: int, border: int, dark: str, light: str) -> str:
    """Standalone <svg> without an XML declaration, safe to inline in HTML."""
    buf = io.BytesIO()
    qr.save(buf, kind="svg", xmldecl=False, svgns=False, nl=False,
            scale=size, border=border, dark=dark, light=light)
    return buf.getvalue().decode("utf-8")


def make_qr(
    qr_token: str,
    *,
    size: int = 6,
    border: int = 2,
    dark: str = "#111111",
    light: str = "#ffffff",
    error_correction: str = "M",
) -> QrPayload:
    """Render the table QR. SVG for print, PNG for sharing."""
    url = build_menu_url(qr_token)
    qr = segno.make(url, error=error_correction)

    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=size, border=border, dark=dark, light=light)

    return QrPayload(
        svg=_inline_svg(qr, size=size, border=border, dark=dark, light=light),
        png=buf.getvalue(),
        url=url,
        filename=f"table-{qr_token}.png",
        size=size,
        error_correction=error_correction,
        modules=[[bool(cell) for cell in row] for row in qr.matrix],
    )


def qr_matrix(qr_token: str, error_correction: str = "M") -> dict[str, Any]:
    """Matrix form, handy for the frontend to draw without a library."""
    qr = segno.make(build_menu_url(qr_token), error=error_correction)
    return {
        "url": build_menu_url(qr_token),
        "size": len(qr.matrix),
        "matrix": [[bool(c) for c in row] for row in qr.matrix],
    }


def svg_grid_sheet(entries: list[tuple[str, str, int]], columns: int = 3) -> str:
    """Print-ready A4 sheet with a QR + table caption for every table."""
    from xml.sax.saxutils import escape

    cell_w, cell_h = 320, 400
    cols = max(1, columns)
    rows = (len(entries) + cols - 1) // cols
    width, height = cell_w * cols, cell_h * max(rows, 1)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    for i, (token, label, seats) in enumerate(entries):
        cx = (i % cols) * cell_w
        cy = (i // cols) * cell_h
        qr = segno.make(build_menu_url(token), error="M")
        parts.append(
            f'<g transform="translate({cx + 50},{cy + 40})">'
            + _inline_svg(qr, size=5, border=2, dark="#000000", light="#ffffff")
            + "</g>"
        )
        parts.append(
            f'<text x="{cx + cell_w / 2}" y="{cy + 320}" text-anchor="middle" '
            f'font-family="Arial, sans-serif" font-size="42" font-weight="bold">{escape(label)}</text>'
        )
        parts.append(
            f'<text x="{cx + cell_w / 2}" y="{cy + 355}" text-anchor="middle" '
            f'font-family="Arial, sans-serif" font-size="24" fill="#555">'
            f"{seats} мест · Меню</text>"
        )
    parts.append("</svg>")
    return "".join(parts)
