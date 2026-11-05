"""Imagens das páginas com as caixas do que foi lido, para conferir um resultado a olho.

Uma imagem por página, com a caixa de cada trecho na cor do leitor que o leu,
a linha que falha uma verificação marcada, e uma legenda das cores. Devolve
imagens, e quem chama decide se as mostra, grava ou junta a outra coisa.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from docaudit import pdf as _pdf
from docaudit.policies import DEFAULT_CHECKS

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from PIL import Image, ImageDraw, ImageFont

    from docaudit.policies import FailsCheck
    from docaudit.types import Result

__all__ = ["visualize"]

# Oito cores que se distinguem em fundo branco; um leitor além do oitavo
# repete a paleta.
_PALETTE = ("#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#8c564b", "#e377c2", "#17becf")


_FAILING = "#000000"
"""O contorno de uma linha cujo valor falha uma verificação."""

_STRIP = 18
"""Altura, em pixels, da faixa da legenda acima de cada página."""


def visualize(
    result: Result,
    document: Path | str | bytes,
    *,
    pages: Iterable[int] | None = None,
    dpi: int = 100,
    show_order: bool = False,
    checks: Sequence[FailsCheck] | None = None,
) -> dict[int, Image.Image]:
    """Cada página de `result` como imagem, com a caixa de cada trecho na cor do leitor.

    A linha cujo valor ainda falha uma verificação, como o erro impresso no
    próprio documento, ganha um contorno preto e grosso por fora da caixa. A
    legenda das cores fica numa faixa acima da página, sem cobrir nada dela.

    Args:
        result: a saída de `process`.
        document: o mesmo documento que `process` recebeu. As páginas são
            renderizadas de novo aqui; o resultado não as guarda.
        pages: os índices a desenhar, zero-based. `None` desenha todas as
            páginas do resultado.
        dpi: resolução das imagens. As caixas são normalizadas e caem no
            lugar em qualquer resolução.
        show_order: escreve, no canto de cada caixa, a posição do trecho na
            ordem de leitura da página.
        checks: as verificações que marcam a linha que falha. `None` usa as
            da política padrão; passe as da sua política quando ela tem
            verificações próprias.

    Returns:
        A imagem de cada página, pelo índice, com a faixa da legenda no alto.
    """
    from PIL import Image, ImageDraw, ImageFont

    # A fonte vetorial que vem com o Pillow. Ela não tem letras acentuadas, e
    # por isso o texto que a biblioteca escreve na imagem é só ASCII.
    font = ImageFont.load_default(size=11)
    if checks is None:
        checks = DEFAULT_CHECKS
    colors = {
        source: _PALETTE[i % len(_PALETTE)]
        for i, source in enumerate(dict.fromkeys(c.source for c in result.chunks))
    }
    by_page = result.by_page()
    wanted = None if pages is None else set(pages)
    out: dict[int, Image.Image] = {}
    with _pdf.opened(document) as handle:
        for page in result.pages:
            if wanted is not None and page.index not in wanted:
                continue
            png = _pdf.render_of(handle, page.index, dpi=dpi)
            with Image.open(io.BytesIO(png)) as rendered:
                sheet = rendered.convert("RGB")
            draw = ImageDraw.Draw(sheet)
            chunks = by_page.get(page.index, [])
            failing = {chunk.id for check in checks for _, chunk in check.failing(page, chunks)}
            for position, chunk in enumerate(chunks):
                box = chunk.bbox.to_pixels(*sheet.size)
                if chunk.id in failing:
                    outset = (box[0] - 3, box[1] - 3, box[2] + 3, box[3] + 3)
                    draw.rectangle(outset, outline=_FAILING, width=3)
                draw.rectangle(box, outline=colors[chunk.source], width=2)
                if show_order:
                    draw.text(
                        (box[0] + 2, box[1] + 1),
                        str(position),
                        fill=colors[chunk.source],
                        font=font,
                    )
            legend = {c.source: colors[c.source] for c in chunks}
            if failing:
                legend["falha numa regra"] = _FAILING
            image = Image.new("RGB", (sheet.width, sheet.height + _STRIP), "white")
            image.paste(sheet, (0, _STRIP))
            _legend(ImageDraw.Draw(image), legend, font)
            out[page.index] = image
    return out


def _legend(
    draw: ImageDraw.ImageDraw,
    colors: dict[str, str],
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
) -> None:
    """Cada nome na sua cor, lado a lado, na faixa do alto da imagem."""
    x = 4
    for name, color in colors.items():
        draw.rectangle((x, 5, x + 7, 12), fill=color)
        draw.text((x + 11, 3), name, fill=color, font=font)
        x += 11 + int(draw.textlength(name, font=font)) + 12
