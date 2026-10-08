# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Monochrome line-icon set for the Point Cloud & Gaussian Splatting panel.

Icons are inline 24×24 SVG strokes (Lucide-style) rendered at runtime with
QtSvg and tinted with the active palette's text colour, so they follow both
light and dark IngeTrazo themes and stay crisp on HiDPI displays.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

try:
    from PySide6.QtSvg import QSvgRenderer
except Exception:  # pragma: no cover - QtSvg is bundled, but stay defensive
    QSvgRenderer = None  # type: ignore[assignment]


_DOTS = '<g fill="currentColor" stroke="none">{}</g>'

# Stroke paths only — colour, width and caps are injected by _svg().
_PATHS: Dict[str, str] = {
    "import": (
        '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v7A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5z"/>'
        '<path d="M12 10.5v5M9.5 13h5"/>'
    ),
    "cloud_points": _DOTS.format(
        '<circle cx="5" cy="13" r="1.3"/><circle cx="8.5" cy="9" r="1.3"/><circle cx="9" cy="15.5" r="1.3"/>'
        '<circle cx="12.5" cy="6.5" r="1.3"/><circle cx="13" cy="12" r="1.3"/><circle cx="13.5" cy="18" r="1.3"/>'
        '<circle cx="16.5" cy="9" r="1.3"/><circle cx="17" cy="14.5" r="1.3"/><circle cx="20" cy="11.5" r="1.3"/>'
    ),
    "splat": (
        '<ellipse cx="9.5" cy="10" rx="6" ry="3.2" transform="rotate(-28 9.5 10)"/>'
        '<ellipse cx="15" cy="15.5" rx="5" ry="2.6" transform="rotate(22 15 15.5)"/>'
        + _DOTS.format('<circle cx="18" cy="6.5" r="1.4"/>')
    ),
    "sample": (
        '<path d="M9 3h6M10 3v6.2L4.6 18.4A1.7 1.7 0 0 0 6.1 21h11.8a1.7 1.7 0 0 0 1.5-2.6L14 9.2V3"/>'
        '<path d="M7.2 15h9.6"/>'
    ),
    "focus": (
        '<path d="M4 9V5.5A1.5 1.5 0 0 1 5.5 4H9M15 4h3.5A1.5 1.5 0 0 1 20 5.5V9'
        'M20 15v3.5a1.5 1.5 0 0 1-1.5 1.5H15M9 20H5.5A1.5 1.5 0 0 1 4 18.5V15"/>'
        '<circle cx="12" cy="12" r="2.8"/>'
    ),
    "cursor": '<path d="M5 4l6.5 16 2.3-6.9L20.5 11z"/><path d="M14 14l5 5"/>',
    "trash": (
        '<path d="M4 7h16M10 11v6M14 11v6"/>'
        '<path d="M6 7l.9 12.2A2 2 0 0 0 8.9 21h6.2a2 2 0 0 0 2-1.8L18 7M9 7V4.5A1.5 1.5 0 0 1 10.5 3h3A1.5 1.5 0 0 1 15 4.5V7"/>'
    ),
    "clear_all": '<path d="M4 6h12M4 12h8M4 18h5"/><path d="M15 15l5 5M20 15l-5 5"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
    "eye_off": (
        '<path d="M3 3l18 18"/>'
        '<path d="M10.6 5.6A9 9 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a16 16 0 0 1-2.8 3.6M6.5 6.9C3.9 8.6 2.5 12 2.5 12S6 18.5 12 18.5a9 9 0 0 0 4.9-1.4"/>'
        '<path d="M10 10a2.8 2.8 0 0 0 4 4"/>'
    ),
    "section": '<path d="M6 2.5V16a2 2 0 0 0 2 2h13.5"/><path d="M18 21.5V8a2 2 0 0 0-2-2H2.5"/>',
    "box": (
        '<path d="M12 2.8l8.2 4.6v9.2L12 21.2l-8.2-4.6V7.4z"/>'
        '<path d="M3.8 7.4L12 12l8.2-4.6M12 12v9.2"/>'
    ),
    "move": (
        '<path d="M12 3v18M3 12h18"/>'
        '<path d="M9.5 5.5L12 3l2.5 2.5M9.5 18.5L12 21l2.5-2.5M5.5 9.5L3 12l2.5 2.5M18.5 9.5L21 12l-2.5 2.5"/>'
    ),
    "rotate_ccw": '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3.5 8.5"/><path d="M3.5 3.5v5h5"/>',
    "rotate_cw": '<path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1l2.6 2.6"/><path d="M20.5 3.5v5h-5"/>',
    "reset": '<path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "scale": (
        '<path d="M14 10l7-7M15 3h6v6"/>'
        '<rect x="3" y="13" width="8" height="8" rx="1.2"/>'
        '<path d="M3 9V4.2A1.2 1.2 0 0 1 4.2 3H9M21 15v4.8a1.2 1.2 0 0 1-1.2 1.2H15"/>'
    ),
    "magnet": (
        '<path d="M6 3.5h4v7.5a2 2 0 0 0 4 0V3.5h4V11a6 6 0 0 1-12 0z"/>'
        '<path d="M6 7.5h4M14 7.5h4"/>'
    ),
    "plane": (
        '<path d="M2.5 18l4.5-7h14.5L17 18z"/>'
        '<path d="M12 14.5V3.5M9.8 5.7L12 3.5l2.2 2.2"/>'
    ),
    "guide": '<path d="M12 21s-6.5-5.6-6.5-11.2a6.5 6.5 0 0 1 13 0C18.5 15.4 12 21 12 21z"/><circle cx="12" cy="9.8" r="2.3"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/>' + _DOTS.format('<circle cx="12" cy="7.8" r="1.1"/>'),
    "ruler": (
        '<path d="M3.5 15.5l12-12 5 5-12 12z"/>'
        '<path d="M7.5 11.5l2 2M10.5 8.5l2 2M13.5 5.5l2 2"/>'
    ),
    "chevron_down": '<path d="M6 9l6 6 6-6"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
}

_cache: Dict[Tuple[str, str, int, float], QPixmap] = {}


def _svg(name: str, color: str, stroke: float = 1.6) -> bytes:
    body = _PATHS[name].replace("currentColor", color)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    ).encode("utf-8")


def _render(name: str, color: QColor, size: int, dpr: float) -> QPixmap:
    hex_rgba = color.name(QColor.HexArgb)
    key = (name, hex_rgba, size, dpr)
    pm = _cache.get(key)
    if pm is not None:
        return pm

    px = max(1, int(round(size * dpr)))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    if QSvgRenderer is not None and name in _PATHS:
        # QtSvg ignores alpha in hex strings: render opaque, apply alpha via painter opacity.
        renderer = QSvgRenderer(QByteArray(_svg(name, color.name(QColor.HexRgb))))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setOpacity(color.alphaF())
        renderer.render(p, QRectF(0, 0, px, px))
        p.end()
    pm.setDevicePixelRatio(dpr)
    _cache[key] = pm
    return pm


def icon_color(palette: Optional[QPalette] = None, role: str = "normal") -> QColor:
    """Return the tint used for icons, derived from the active palette."""
    pal = palette or QApplication.palette()
    base = QColor(pal.color(QPalette.WindowText))
    if role == "disabled":
        base.setAlphaF(0.32)
    elif role == "muted":
        base.setAlphaF(0.62)
    elif role == "active":
        base = QColor(pal.color(QPalette.HighlightedText))
    return base


def make_icon(name: str, size: int = 16, palette: Optional[QPalette] = None) -> QIcon:
    """Build a palette-tinted monochrome QIcon (normal, disabled, selected/active states)."""
    app = QApplication.instance()
    dpr = 2.0
    try:
        if app is not None and app.primaryScreen() is not None:
            dpr = max(1.0, float(app.primaryScreen().devicePixelRatio()))
    except Exception:
        pass

    ic = QIcon()
    for mode, role in (
        (QIcon.Normal, "normal"),
        (QIcon.Disabled, "disabled"),
        (QIcon.Active, "normal"),
        (QIcon.Selected, "active"),
    ):
        ic.addPixmap(_render(name, icon_color(palette, role), size, dpr), mode, QIcon.Off)
    return ic


def clear_cache() -> None:
    """Drop cached pixmaps (call on palette/theme change)."""
    _cache.clear()


__all__ = ["make_icon", "icon_color", "clear_cache"]
