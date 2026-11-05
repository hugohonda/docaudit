"""A ordem por layout: blocos do detector, de cima para baixo dentro de cada um."""

from docaudit.process import _order_by_layout
from docaudit.types import BBox, Chunk, Region


def _line(x0: float, y0: float, text: str, kind: str | None = None) -> Chunk:
    bbox = BBox(x0=x0, y0=y0, x1=x0 + 0.4, y1=y0 + 0.02)
    return Chunk(id=text, page=0, bbox=bbox, text=text, source="ocr", kind=kind)


LEFT = Region(label="text", bbox=BBox(x0=0.05, y0=0.1, x1=0.48, y1=0.9))
RIGHT = Region(label="table", bbox=BBox(x0=0.52, y0=0.1, x1=0.95, y1=0.9))


def test_two_columns_come_out_one_after_the_other():
    """O OCR entregou as linhas pela altura: esquerda, direita, esquerda, direita."""
    lines = [
        _line(0.05, 0.1, "E1"),
        _line(0.52, 0.1, "D1"),
        _line(0.05, 0.3, "E2"),
        _line(0.52, 0.3, "D2"),
    ]
    ordered = _order_by_layout(lines, [LEFT, RIGHT])
    assert [c.text for c in ordered] == ["E1", "E2", "D1", "D2"]
    assert [c.reading_order for c in ordered] == [0, 1, 2, 3]
    assert [c.kind for c in ordered] == ["text", "text", "table", "table"]


def test_a_line_outside_every_block_goes_to_the_nearest_and_keeps_its_kind():
    header = _line(0.3, 0.02, "cabeçalho", kind="header")
    ordered = _order_by_layout([_line(0.52, 0.5, "D1"), header], [LEFT, RIGHT])
    assert [c.text for c in ordered] == ["cabeçalho", "D1"]
    assert ordered[0].kind == "header"


def test_without_blocks_the_order_is_left_as_it_came():
    lines = [_line(0.52, 0.1, "D1"), _line(0.05, 0.1, "E1")]
    assert _order_by_layout(lines, []) == lines
