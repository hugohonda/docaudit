"""As regras pequenas da cascata que são nomes públicos, para quem mede o que ela faz."""

from types import SimpleNamespace

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from tests.support import make_scanned_pdf

from docaudit.backends.ppocr import turned
from docaudit.pdf import page_bounds
from docaudit.process import form_of, within
from docaudit.types import BBox, Chunk


def _chunk(x0: float, y0: float, x1: float, y1: float) -> Chunk:
    bbox = BBox(x0=x0, y0=y0, x1=x1, y1=y1)
    return Chunk(
        id=Chunk.make_id("doc", bbox, "leitor", "linha", page=0),
        page=0,
        bbox=bbox,
        text="linha",
        source="leitor",
        confidence=0.9,
    )


def test_two_lines_that_differ_only_in_numbers_have_the_same_form():
    assert form_of("fls. 12") == form_of("fls.  13")
    assert form_of("Página 2 de IX") == "página @ de @"
    assert form_of("fls. 12") != form_of("pág. 12")


def test_a_line_centred_in_the_region_is_kept_with_its_box_held_inside():
    box = BBox(x0=0.2, y0=0.2, x1=0.6, y1=0.6)
    inside = _chunk(0.3, 0.3, 0.5, 0.4)
    spills = _chunk(0.3, 0.5, 0.8, 0.56)
    outside = _chunk(0.7, 0.7, 0.9, 0.8)
    kept = within([inside, spills, outside], box)
    assert [c.bbox for c in kept] == [inside.bbox, BBox(x0=0.3, y0=0.5, x1=0.6, y1=0.56)]
    assert kept[0] is inside, "a linha que já cabe volta como veio"


def test_an_object_inside_a_form_is_placed_where_the_form_draws_it():
    document = pdfium.PdfDocument(
        make_scanned_pdf(
            ["Esta edição encontra-se no site da prefeitura"],
            render_mode=0,
            text_before_image=True,
            raster_box=(0.0, 0.5, 1.0, 1.0),
            text_in_form=True,
        )
    )
    page = document[0]
    (text,) = page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_TEXT], max_depth=5)
    _, raw_bottom, _, _ = text.get_bounds()
    _, bottom, _, top = page_bounds(text)
    assert raw_bottom < page.get_height() / 2 < bottom < top <= page.get_height()


def test_a_crop_whose_orientation_differs_from_its_box_was_turned():
    tall_box = [(0, 0), (10, 0), (10, 40), (0, 40)]
    assert turned(tall_box, SimpleNamespace(shape=(10, 40, 3)))
    assert not turned(tall_box, SimpleNamespace(shape=(40, 10, 3)))
