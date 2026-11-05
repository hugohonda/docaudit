"""Backend de OCR barato sobre o Tesseract.

Roda em CPU, em qualquer máquina, sem peso de modelo para baixar. Pede o extra
`tesseract` e o binário no sistema.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, NamedTuple, cast

from docaudit.types import BBox, Chunk

if TYPE_CHECKING:
    from collections.abc import Sequence

    from docaudit.pdf import PageView
    from docaudit.types import Page

__all__ = ["TesseractOCR"]


_NO_BINARY = (
    "binário do Tesseract não encontrado; instale com `brew install tesseract tesseract-lang`"
    " ou `apt install tesseract-ocr tesseract-ocr-por`"
)


class TesseractOCR:
    """Lê uma página com o Tesseract e devolve um chunk por linha.

    A linha é a unidade que o Tesseract agrupa de forma confiável. Palavras dão
    caixas boas e texto fragmentado; blocos dão um despejo de página inteira.
    """

    name = "tesseract"
    external = False

    def __init__(self, lang: str | None = None, config: str = "") -> None:
        """Configura idioma e flags do motor.

        Args:
            lang: código de idioma do Tesseract. `None` lê
                `DOCAUDIT_OCR_LANG`, cujo padrão é `por`, porque o pacote é
                para documentos em português. Precisa do pacote de idioma
                instalado.
            config: flags extras, por exemplo `--psm 6` para página de bloco
                único.
        """
        self.lang = lang if lang is not None else os.environ.get("DOCAUDIT_OCR_LANG", "por")
        self.config = config
        self._output_version: str | None = None

    @property
    def output_version(self) -> str:
        """Idioma, flags e versão do binário: tudo o que muda a leitura.

        A versão do binário vem de um subprocesso, por isso é lida uma vez e só
        quando alguém pergunta: o cache, ou a verificação do contrato.
        """
        if self._output_version is None:
            import pytesseract

            try:
                binary = str(pytesseract.get_tesseract_version())
            except pytesseract.TesseractNotFoundError as exc:
                raise OSError(_NO_BINARY) from exc
            self._output_version = f"1:tesseract={binary}:lang={self.lang}:config={self.config}"
        return self._output_version

    def read(self, view: PageView) -> Sequence[Chunk]:
        """Transcreve a página inteira, uma linha por chunk."""
        image = view.image()
        page = view.page
        import io

        try:
            import pytesseract
        except ModuleNotFoundError as exc:  # pragma: no cover - depende do ambiente
            raise ModuleNotFoundError(
                "o backend 'tesseract' precisa do extra: uv add 'docaudit[tesseract]' "
                "(e do binário tesseract no sistema)"
            ) from exc

        from PIL import Image

        with Image.open(io.BytesIO(image)) as img:
            # O pytesseract sempre grava um arquivo temporário, no formato que a
            # imagem declara; como `Image.open` sobre bytes de PNG marca
            # `format="PNG"`, ele re-comprime PNG à toa. Trocar o rótulo para
            # TIFF é sem perda e evita recomprimir.
            img.load()
            img.format = "TIFF"
            # `output_type=DICT` garante o dicionário; o stub declara a união
            # de todos os formatos de saída, e o parâmetro `image` sem tipo.
            try:
                data = cast(
                    "dict[str, list[Any]]",
                    pytesseract.image_to_data(  # pyright: ignore[reportUnknownMemberType]
                        img,
                        lang=self.lang,
                        config=self.config,
                        output_type=pytesseract.Output.DICT,
                    ),
                )
            except pytesseract.TesseractNotFoundError as exc:
                raise OSError(_NO_BINARY) from exc
            width, height = img.size

        return [
            self._chunk(page, line, order, width, height) for order, line in enumerate(_lines(data))
        ]

    def _chunk(self, page: Page, line: _Line, order: int, width: int, height: int) -> Chunk:
        bbox = BBox.from_pixels(
            line.x0, line.y0, line.x1, line.y1, width_px=width, height_px=height
        )
        return Chunk.make(
            page, bbox, self.name, line.text, confidence=line.confidence, reading_order=order
        )


class _Line(NamedTuple):
    """Uma linha do Tesseract: caixa do nível 4, texto e confiança dos níveis 5."""

    text: str
    x0: int
    y0: int
    x1: int
    y1: int
    confidence: float


_LEVEL_LINE = 4
_LEVEL_WORD = 5


def _lines(data: dict[str, list[Any]]) -> list[_Line]:
    """Agrupa a tabela plana de `image_to_data` em linhas.

    O Tesseract já devolve uma linha de nível 4 por linha de texto, e a caixa
    dela coincide com a união das caixas das palavras, então ela é lida direto
    em vez de recalculada. O que o nível 4 não traz é texto nem confiança (vem
    com `conf == -1`), então as palavras do nível 5 continuam necessárias para
    esses dois campos.
    """
    boxes: dict[tuple[int, int, int], tuple[int, int, int, int]] = {}
    words: dict[tuple[int, int, int], list[int]] = {}

    for i, level in enumerate(data["level"]):
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        if level == _LEVEL_LINE:
            left, topo = int(data["left"][i]), int(data["top"][i])
            boxes[key] = (
                left,
                topo,
                left + int(data["width"][i]),
                topo + int(data["height"][i]),
            )
        elif level == _LEVEL_WORD and str(data["text"][i]).strip():
            words.setdefault(key, []).append(i)

    out: list[_Line] = []
    for key in sorted(words):
        idx = words[key]
        # Tesseract devolve confiança em [0, 100]; -1 marca "sem estimativa".
        confs = [float(data["conf"][i]) for i in idx if float(data["conf"][i]) >= 0]
        x0, y0, x1, y1 = boxes[key]
        out.append(
            _Line(
                text=" ".join(str(data["text"][i]) for i in idx),
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                confidence=(sum(confs) / len(confs) / 100.0) if confs else 0.0,
            )
        )
    return out
