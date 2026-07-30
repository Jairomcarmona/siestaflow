"""Explicit renderer for preserved FDF documents."""

from .models import FDFDocument


class FDFRenderer:
    def render(self, document: FDFDocument) -> str:
        return document.render()
