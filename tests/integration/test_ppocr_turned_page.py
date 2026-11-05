"""Uma página digitalizada de lado é lida em pé, e as caixas voltam no sistema da imagem.

Marcado `slow`: usa o PP-OCR de verdade.
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO

import pytest
from tests.support.fixtures import _font

import docaudit

pytestmark = [pytest.mark.slow, pytest.mark.integration]
pytest.importorskip("rapidocr", reason="precisa do extra `ppocr`")

from docaudit.backends.ppocr import PPOCR  # noqa: E402

ROWS = [
    ("Alfa Beta Ltda", "12.345,67"),
    ("Gama Delta", "8.901,23"),
    ("Epsilon", "4.567,89"),
]
STAMP = "Este documento foi assinado digitalmente fls. 1234"


def _sideways_table(
    angle: int, rows: Sequence[tuple[str, str]] = ROWS, stamp: bool = False
) -> bytes:
    """Uma tabela de duas colunas girada `angle` graus (anti-horário), num PDF só de imagem.

    Com `stamp`, a margem direita leva uma tarja escrita de baixo para cima.
    """
    from PIL import Image, ImageDraw

    dpi = 200
    font = _font(int(dpi * 0.13))
    if font is None:  # pragma: no cover
        pytest.skip("nenhuma font monoespaçada TrueType disponível")
    img = Image.new("L", (int(8.27 * dpi), int(11.69 * dpi)), 255)
    draw = ImageDraw.Draw(img)
    for i, (name, value) in enumerate(rows):
        y = int(dpi * (1.0 + 0.4 * i))
        draw.text((int(dpi * 0.8), y), name, fill=20, font=font)
        draw.text((int(dpi * 6.0), y), value, fill=20, font=font)
    if stamp:
        band = Image.new("L", (int(dpi * 4.5), int(dpi * 0.3)), 255)
        ImageDraw.Draw(band).text((5, 5), STAMP, fill=20, font=font)
        img.paste(band.rotate(90, expand=True), (int(dpi * 7.7), int(dpi * 3.0)))
    buf = BytesIO()
    img.rotate(angle, expand=True).save(buf, format="PDF", resolution=float(dpi))
    return buf.getvalue()


@pytest.mark.parametrize(("angle", "turn"), [(90, 270), (270, 90)])
def test_a_sideways_table_is_read_upright_with_boxes_on_the_image(angle: int, turn: int) -> None:
    result = docaudit.process(_sideways_table(angle), policy="all_cheap", cheap=[PPOCR()])
    chunks = {c.text.strip(): c for c in result.chunks}

    for name, value in ROWS:
        assert name in chunks, sorted(chunks)
        assert value in chunks, sorted(chunks)
        a, b = chunks[name], chunks[value]
        assert a.turn == turn
        assert b.turn == turn
        # On the sideways image a table row is a vertical band: name and value share its x range.
        assert min(a.bbox.x1, b.bbox.x1) > max(a.bbox.x0, b.bbox.x0)
    order = [chunks[name].reading_order or 0 for name, _ in ROWS]
    assert order == sorted(order)


def test_an_upright_page_is_not_turned() -> None:
    result = docaudit.process(_sideways_table(0), policy="all_cheap", cheap=[PPOCR()])
    assert result.chunks
    assert all(c.turn == 0 for c in result.chunks)


def test_a_sparse_upright_page_with_a_margin_stamp_stays_upright() -> None:
    """A tarja em pedaços faz maioria alta numa página de uma linha; girada, o corpo é que parte."""
    pdf = _sideways_table(0, rows=[("Valor total 1.249,01", "")], stamp=True)
    result = docaudit.process(pdf, policy="all_cheap", cheap=[PPOCR()])
    texts = [c.text.strip() for c in result.chunks]

    assert all(c.turn == 0 for c in result.chunks), texts
    assert "Valor total 1.249,01" in texts, texts
