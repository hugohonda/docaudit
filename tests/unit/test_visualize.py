"""As imagens de inspeção: uma por página, uma caixa por trecho, na cor do leitor."""

import io

from PIL import Image
from tests.support import FakeVLM, make_pdf, make_scanned_pdf
from tests.support.fixtures import EMPTY_PAGE, TEXT_CENTRAL

from docaudit import process, visualize
from docaudit.pdf import opened, render_of
from docaudit.visualize import _STRIP


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)


def test_one_image_per_page_with_each_box_in_the_color_of_its_reader():
    doc = make_scanned_pdf(["PODER JUDICIARIO", "CPF 529.982.247-27"])
    result = process(
        doc,
        policy="evidence",
        cheap=["text_layer"],
        strong=FakeVLM(text="CPF 529.982.247-25"),
        reread="region",
        trust_layer="always",
    )
    images = visualize(result, doc)
    assert list(images) == [p.index for p in result.pages]
    image = images[0]
    colors = {c.source for c in result.chunks}
    assert colors == {"text_layer", "fake-vlm"}, "a linha barata e a cara, em cores diferentes"
    for chunk in result.chunks:
        x0, y0, _, _ = chunk.bbox.to_pixels(image.width, image.height - _STRIP)
        expected = "#1f77b4" if chunk.source == result.chunks[0].source else "#d62728"
        assert image.getpixel((x0 + 1, y0 + _STRIP)) == _rgb(expected)


def test_the_resolution_is_the_one_asked_and_the_boxes_follow_it():
    doc = make_pdf(TEXT_CENTRAL)
    result = process(doc, policy="all_cheap", cheap=["text_layer"])
    small, large = visualize(result, doc, dpi=50)[0], visualize(result, doc, dpi=100)[0]
    assert abs(large.width - 2 * small.width) <= 1, "o pdfium arredonda o pixel para cima"
    (chunk,) = result.chunks
    x0, y0, _, _ = chunk.bbox.to_pixels(large.width, large.height - _STRIP)
    assert large.getpixel((x0 + 1, y0 + _STRIP)) == _rgb("#1f77b4")


def test_only_the_pages_asked_are_drawn():
    doc = make_pdf(*[TEXT_CENTRAL] * 3)
    result = process(doc, policy="all_cheap", cheap=["text_layer"])
    assert list(visualize(result, doc, pages=[2])) == [2]


def test_a_page_where_nothing_was_read_is_drawn_without_boxes():
    doc = make_pdf(EMPTY_PAGE)
    result = process(doc, policy="all_cheap", cheap=["text_layer"])
    image = visualize(result, doc)[0]
    assert image.getcolors(maxcolors=4) == [(image.width * image.height, (255, 255, 255))]


def test_a_line_that_still_fails_a_check_is_framed_and_named_in_the_legend():
    """O CPF que a releitura não consertou é o erro impresso no documento: fica marcado."""
    doc = make_scanned_pdf(["PODER JUDICIARIO", "CPF 529.982.247-27"])
    result = process(doc, policy="evidence", cheap=["text_layer"], trust_layer="always")
    image = visualize(result, doc)[0]
    failing = next(c for c in result.chunks if "CPF" in c.text)
    clean = next(c for c in result.chunks if "PODER" in c.text)
    for chunk, framed in ((failing, True), (clean, False)):
        x0, y0, _, _ = chunk.bbox.to_pixels(image.width, image.height - _STRIP)
        pixel = image.getpixel((x0 + 1, y0 + _STRIP - 2))
        assert (pixel == (0, 0, 0)) is framed
    strip = image.crop((0, 0, image.width, _STRIP))
    colors = strip.getcolors(maxcolors=strip.width * strip.height) or []
    assert (0, 0, 0) in {color for _, color in colors}, "na legenda"


def test_the_legend_is_a_strip_above_the_page_and_covers_nothing():
    doc = make_pdf(TEXT_CENTRAL)
    result = process(doc, policy="all_cheap", cheap=["text_layer"])
    framed = visualize(result, doc, dpi=50)[0]
    with opened(doc) as handle:
        bare = render_of(handle, 0, dpi=50)
    with Image.open(io.BytesIO(bare)) as page:
        assert framed.size == (page.width, page.height + _STRIP)
