"""Ponta a ponta com o Tesseract de verdade, sobre um edital escaneado sintético.

Marcado `slow` porque depende do binário do Tesseract com o pacote de idioma
`por` instalado; a CI do Linux faz `apt-get install tesseract-ocr-por`. Roda com
`uv run pytest -m slow`.

O que este arquivo cobre e os testes com fakes não cobrem: que a classificação
de substrato, a renderização, o motor de OCR real e a triagem sob orçamento se
encaixam, e que um valor lido volta com página e caixa utilizáveis.
"""

from __future__ import annotations

import pytest
from tests.support import FakeVLM, make_scanned_pdf
from tests.support.contracts import ReaderContract
from tests.support.fixtures import make_notice_pdf

import docaudit
from docaudit import Budget, Substrate, Tier
from docaudit.backends.tesseract import TesseractOCR
from docaudit.pdf import load_pages

pytestmark = [pytest.mark.slow, pytest.mark.integration]

pytest.importorskip("pytesseract", reason="precisa do extra `tesseract`")


@pytest.fixture(scope="module")
def tesseract_available() -> None:
    import pytesseract

    try:
        langs = pytesseract.get_languages()
    except (OSError, pytesseract.TesseractNotFoundError) as exc:  # pragma: no cover
        pytest.skip(f"binário do Tesseract indisponível: {exc}")
    if "por" not in langs:  # pragma: no cover
        pytest.skip("pacote de idioma `por` do Tesseract não instalado")


@pytest.fixture
def escaneado() -> bytes:
    """Uma página: raster de página inteira, sem camada de texto."""
    return make_scanned_pdf()


def test_substrate_of_a_scanned_case_file(escaneado: bytes) -> None:
    """Um raster de página inteira sem texto é IMAGE_ONLY, e precisa de OCR."""
    page = load_pages(escaneado)[0]
    assert page.substrate is Substrate.IMAGE_ONLY
    assert page.substrate_evidence["chars"] == 0.0


@pytest.mark.usefixtures("tesseract_available")
def test_reads_the_notice_end_to_end() -> None:
    """O caminho completo: página escaneada, OCR real, chunks com proveniência."""
    doc = make_notice_pdf()
    result = docaudit.process(doc, policy="all_cheap", cheap=[TesseractOCR(lang="por")])

    assert result.spent.pages_strong == 0.0
    assert result.chunks, "o OCR não devolveu nada"

    text_value = " ".join(c.text for c in result.chunks).upper()
    assert "INTERESSADOS" in text_value
    assert "ANDRADE" in text_value, f"não achou o nome no text_value lido: {text_value[:200]!r}"
    assert "1000123-47.2024.8.26.0100" in text_value.replace(" ", "")

    for chunk in result.chunks:
        assert chunk.source == "tesseract"
        assert chunk.reading_order is not None
        assert 0.0 <= chunk.bbox.x0 <= chunk.bbox.x1 <= 1.0
        assert 0.0 <= chunk.bbox.y0 <= chunk.bbox.y1 <= 1.0
        assert chunk.confidence is not None


@pytest.mark.usefixtures("tesseract_available")
def test_reading_order_follows_the_page() -> None:
    """A ordem de leitura tem de ser monotônica de cima para baixo."""
    result = docaudit.process(
        make_notice_pdf(), policy="all_cheap", cheap=[TesseractOCR(lang="por")]
    )
    ordered = sorted(result.chunks, key=lambda c: c.reading_order or 0)
    topos = [c.bbox.y0 for c in ordered]
    assert topos == sorted(topos), "order de leitura não acompanha a posição vertical"


@pytest.mark.usefixtures("tesseract_available")
def test_each_value_comes_back_with_a_usable_page_and_box() -> None:
    """Grounding mínimo: recortar a caixa devolve o texto que ela promete."""
    doc = make_notice_pdf()
    result = docaudit.process(doc, policy="all_cheap", cheap=[TesseractOCR(lang="por")])

    alvo = next(c for c in result.chunks if "ANDRADE" in c.text.upper())
    page = load_pages(doc)[alvo.page]
    px = alvo.bbox.to_pixels(page.dimensions.width_px, page.dimensions.height_px)
    assert px[0] < px[2], "caixa degenerada na horizontal"
    assert px[1] < px[3], "caixa degenerada na vertical"

    # O recorte tem de conter o mesmo valor: é a definição de precisão de citação
    # do documento 2, §4, no caso mais simples.
    import io

    import pytesseract
    from PIL import Image

    from docaudit.pdf import opened, render_of

    with opened(doc) as pdf, Image.open(io.BytesIO(render_of(pdf, alvo.page))) as img:
        crop = img.crop(px)
    reread = pytesseract.image_to_string(crop, lang="por").upper()
    assert "ANDRADE" in reread, f"o crop da caixa não contém o valor: {reread!r}"


@pytest.mark.usefixtures("tesseract_available")
def test_triage_under_budget_escalates_only_what_is_allowed() -> None:
    """A triagem sob orçamento, com OCR real na passagem barata."""

    doc = make_scanned_pdf()
    vlm = FakeVLM()
    result = docaudit.process(
        doc,
        policy="evidence",
        budget=Budget(max_strong_pages=1),
        cheap=[TesseractOCR(lang="por")],
        strong=vlm,
    )
    assert vlm.calls == 1
    assert result.spent.pages_strong == 1.0
    assert sum(d.tier is Tier.STRONG for d in result.decisions) == 1


class TestTesseractContract(ReaderContract):
    @pytest.fixture
    def reader(self):
        return TesseractOCR()
