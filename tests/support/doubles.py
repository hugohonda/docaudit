"""Dublês compartilhados pelas suítes."""

from __future__ import annotations

from docaudit.types import BBox, Chunk

__all__ = ["FakeVLM"]


class FakeVLM:
    """Leitura cara falsa, com contador de chamadas para testar o cache."""

    name = "fake-vlm"
    external = False
    output_version = "v1"

    def __init__(self, box: BBox | None = None, text: str | None = None):
        """`box` é a região lida; sem ela, a página inteira, como um VLM sem layout.

        `text` é o que o leitor devolve; sem ele, um texto que não traz valor
        nenhum, e que a leitura cara recusa onde a barata tinha um valor.
        """
        self.calls = 0
        self.box = box or BBox(x0=0.0, y0=0.0, x1=1.0, y1=1.0)
        self.text = text

    def read(self, view):
        self.calls += 1
        view.image(grayscale=False)
        page = view.page
        text = self.text or f"vlm pagina {page.index}"
        return [Chunk.make(page, self.box, self.name, text, confidence=0.95)]
