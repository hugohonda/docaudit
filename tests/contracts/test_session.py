"""`Document`: ler, listar as dúvidas, reler um recorte e recortar, sem reabrir o documento.

As páginas são digitalizações com camada de OCR embutida, lidas com
`trust_layer="always"`: é a camada que traz o CPF que falha.
"""

import io

import pytest
from PIL import Image
from tests.support import FakeVLM, make_scanned_pdf

from docaudit import Budget, Document, Doubt, process
from docaudit.cache import ModelCallCache
from docaudit.types import BBox, ExternalBackendError, Tier


def test_read_matches_process_and_doubts_point_to_the_failing_line():
    doc_bytes = make_scanned_pdf(["PODER JUDICIARIO", "CPF 529.982.247-27", "Valor R$ 10,00"])
    with Document(doc_bytes, cheap=["text_layer"], trust_layer="always") as doc:
        result = doc.read()
        assert [c.text for c in result.chunks] == [
            c.text
            for c in process(
                doc_bytes, policy="evidence", cheap=["text_layer"], trust_layer="always"
            ).chunks
        ]
        assert result.decisions[0].tier is Tier.STRONG
        doubts = doc.doubts(result)
        assert [(d.check, d.value) for d in doubts] == [("CPF", "529.982.247-27")]
        assert isinstance(doubts[0], Doubt)
        assert "CPF" in doubts[0].chunk.text


def test_a_doubt_carries_the_reading_of_the_reader_that_did_not_replace_it():
    doc_bytes = make_scanned_pdf(["CPF 529.982.247-27"])
    other = FakeVLM(text="CPF 529.982.247-27")
    with Document(doc_bytes, cheap=["text_layer"], confirm=other, trust_layer="always") as doc:
        (doubt,) = doc.doubts(doc.read())
    (reading,) = doubt.others
    assert reading.line == doubt.chunk.id
    assert reading.reading.source == "fake-vlm"
    assert reading.same, "o outro leitor leu o mesmo CPF inválido"


def test_reread_reads_only_the_box_and_crop_returns_that_png(tmp_path):
    doc_bytes = make_scanned_pdf(["PODER JUDICIARIO", "CPF 529.982.247-27"])
    vlm = FakeVLM()
    cache = ModelCallCache(tmp_path / "c.sqlite")
    with Document(doc_bytes, cheap=["text_layer"], trust_layer="always", cache=cache) as doc:
        result = doc.read()
        doubt = doc.doubts(result)[0]
        lines = doc.reread(doubt.chunk.page, doubt.chunk.bbox, vlm)
        assert vlm.calls == 1
        assert len(lines) == 1
        box = lines[0].bbox
        assert (box.x0, box.y0, box.x1, box.y1) == pytest.approx(
            (doubt.chunk.bbox.x0, doubt.chunk.bbox.y0, doubt.chunk.bbox.x1, doubt.chunk.bbox.y1),
            abs=1e-3,
        )
        assert result.chunks == doc.read().chunks, "reler não mexe no resultado"
        assert doc.reread(doubt.chunk.page, doubt.chunk.bbox, vlm) == lines
        assert vlm.calls == 1, "o recorte vem do cache"

        png = doc.crop(doubt.chunk.page, doubt.chunk.bbox)
        with Image.open(io.BytesIO(png)) as img:
            width, height = img.size
        page = result.pages[0].dimensions
        assert width == pytest.approx(
            page.width_px * (doubt.chunk.bbox.x1 - doubt.chunk.bbox.x0), abs=2
        )
        assert height < page.height_px / 4
    cache.close()


def test_render_is_the_whole_page_the_readers_saw():
    doc_bytes = make_scanned_pdf(["PODER JUDICIARIO", "CPF 529.982.247-27"])
    with Document(doc_bytes, cheap=["text_layer"], trust_layer="always") as doc:
        page = doc.read().pages[0].dimensions
        whole = BBox(x0=0.0, y0=0.0, x1=1.0, y1=1.0)
        rendered = doc.render(0, grayscale=False)
        cropped = doc.crop(0, whole, grayscale=False)
        with Image.open(io.BytesIO(rendered)) as img, Image.open(io.BytesIO(cropped)) as same:
            assert img.size == (page.width_px, page.height_px)
            assert img.mode == "RGB"
            assert img.tobytes() == same.tobytes(), "os mesmos pixels que o recorte da página toda"
        with Image.open(io.BytesIO(doc.render(0))) as img:
            assert img.mode == "L"
        with pytest.raises(IndexError, match="índices de 0 a 0"):
            doc.render(1)


def test_budget_and_pages_pass_through():
    doc_bytes = make_scanned_pdf(["CPF 529.982.247-27"])
    with Document(doc_bytes, cheap=["text_layer"], strong=FakeVLM(), trust_layer="always") as doc:
        kept = doc.read(budget=Budget(max_strong_pages=0))
        assert kept.spent.pages_strong == 0.0
        assert doc.read(pages=[0]).spent.pages_total == 1.0


class _Leaky(FakeVLM):
    name = "leaky"
    external = True


def test_an_external_reader_is_refused_at_open_and_at_reread():
    doc_bytes = make_scanned_pdf(["CPF 529.982.247-27"])
    with pytest.raises(ExternalBackendError):
        Document(doc_bytes, cheap=["text_layer"], strong=_Leaky())
    with Document(doc_bytes, cheap=["text_layer"], trust_layer="always") as doc:
        result = doc.read()
        doubt = doc.doubts(result)[0]
        with pytest.raises(ExternalBackendError):
            doc.reread(0, doubt.chunk.bbox, _Leaky())


def test_a_closed_document_and_an_unknown_page_fail_with_a_clear_error():
    doc_bytes = make_scanned_pdf(["CPF 529.982.247-27"])
    box = BBox(x0=0.1, y0=0.1, x1=0.5, y1=0.2)
    doc = Document(doc_bytes, cheap=["text_layer"], trust_layer="always")
    with pytest.raises(IndexError, match="índices de 0 a 0"):
        doc.crop(5, box)
    doc.close()
    doc.close()
    with pytest.raises(ValueError, match="documento fechado"):
        doc.crop(0, box)
    with pytest.raises(ValueError, match="documento fechado"):
        doc.read()
