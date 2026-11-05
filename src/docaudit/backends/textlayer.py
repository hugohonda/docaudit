"""Leitor da camada de texto embutida no PDF.

É o leitor mais barato que existe: o texto já está no arquivo, com coordenadas,
e extraí-lo não custa modelo nem renderização.

Lê tanto a camada composta de um `BORN_DIGITAL` quanto a camada que um motor de
OCR deixou num `SEARCHABLE_SCAN`. A segunda tem qualidade desconhecida, mas
trocá-la por outro OCR barato só troca um erro desconhecido por outro, a um
custo de centenas de milissegundos por página. O que decide se ela precisa de
uma releitura é a evidência no texto lido, e isso é papel da política
`evidence`. `Page.substrate` continua dizendo de onde o texto veio.

É um backend registrado como qualquer outro: pode ser reordenado ou removido da
cascata pelo chamador.
"""

from __future__ import annotations

from importlib.metadata import version
from typing import TYPE_CHECKING

from docaudit.types import Chunk

if TYPE_CHECKING:
    from collections.abc import Sequence

    from docaudit.pdf import PageView

__all__ = ["TextLayerReader"]


class TextLayerReader:
    """Devolve um chunk por linha do texto que o PDF já carrega."""

    name = "text_layer"
    external = False
    # O pdfium monta as linhas, e `text_lines_of` as põe na ordem da folha:
    # trocar qualquer dos dois pode mudar a saída.
    output_version = "3:pypdfium2=" + version("pypdfium2")

    def read(self, view: PageView) -> Sequence[Chunk]:
        """Um chunk por linha, na ordem do texto do pdfium, que nem sempre é a do desenho."""
        page = view.page
        return [
            Chunk.make(
                page,
                line.bbox,
                self.name,
                line.text,
                reading_order=order,
                line_break_hyphens=line.hyphens,
            )
            for order, line in enumerate(view.text_lines())
        ]
