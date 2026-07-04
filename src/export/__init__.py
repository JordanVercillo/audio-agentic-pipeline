"""
src.export — Static portfolio export (SPEC P4)
================================================
Renders the shareable single-file taste report from the gold layer and the
artifact PNGs. No server, no external assets — everything inlined.

    >>> from src.export.portfolio import build_report_html
"""

from .portfolio import build_report_html, render_html

__all__ = ["build_report_html", "render_html"]
