import pytest
from pydantic import ValidationError

from docaudit.types import BBox, Budget, Chunk, PageDimensions


def test_bbox_rejects_inverted_corners():
    with pytest.raises(ValidationError):
        BBox(x0=0.8, y0=0.1, x1=0.2, y1=0.9)


def test_bbox_rejects_out_of_unit_range():
    with pytest.raises(ValidationError):
        BBox(x0=0.0, y0=0.0, x1=1.5, y1=1.0)


def test_pixel_roundtrip():
    a = BBox(x0=0.1, y0=0.2, x1=0.6, y1=0.8)
    px = a.to_pixels(1000, 2000)
    back = BBox.from_pixels(*px, width_px=1000, height_px=2000)
    assert (back.x0, back.y0, back.x1, back.y1) == pytest.approx((a.x0, a.y0, a.x1, a.y1), abs=1e-3)


@pytest.mark.parametrize(
    ("width_pt", "height_pt", "paper"),
    [
        (595.0, 842.0, "A4"),
        (842.0, 595.0, "A4"),
        (612.0, 792.0, "Letter"),
        (612.0, 936.0, "Ofício"),
        (500.0, 500.0, None),
        (595.0, 900.0, None),
    ],
)
def test_the_paper_format_comes_from_the_points_in_either_orientation(width_pt, height_pt, paper):
    dims = PageDimensions(width_pt=width_pt, height_pt=height_pt, width_px=10, height_px=10, dpi=72)
    assert dims.paper == paper


def test_chunk_id_is_deterministic_and_text_sensitive():
    bbox = BBox(x0=0.0, y0=0.0, x1=1.0, y1=1.0)
    a = Chunk.make_id("deadbeef", bbox, "tesseract", "linha A", page=0)
    b = Chunk.make_id("deadbeef", bbox, "tesseract", "linha A", page=0)
    c = Chunk.make_id("deadbeef", bbox, "tesseract", "linha B", page=0)
    assert a == b
    assert a != c


def test_chunk_is_frozen():
    bbox = BBox(x0=0.0, y0=0.0, x1=1.0, y1=1.0)
    chunk = Chunk(id="x", page=0, bbox=bbox, text="t", source="s")
    with pytest.raises(ValidationError):
        chunk.text = "outro"


@pytest.mark.parametrize(
    ("budget", "total", "expected"),
    [
        (Budget(), 100, None),
        (Budget(max_strong_pages=10), 100, 10),
        (Budget(max_strong_fraction=0.2), 100, 20),
        (Budget(max_strong_pages=10, max_strong_fraction=0.5), 100, 10),
        (Budget(max_strong_fraction=0.2), 7, 2),
        (Budget(max_strong_fraction=0.2), 4, 1),
    ],
)
def test_page_allowance_takes_the_tightest_cap(budget, total, expected):
    assert budget.page_allowance(total) == expected
