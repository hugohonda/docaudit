"""Ponta a ponta com um `llama-server` de verdade e com o detector de layout.

Pula sem servidor. `DOCAUDIT_VLM_URL` aponta para outro endereço. O teste do
detector baixa os pesos na primeira execução.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

import pytest
from tests.support import ReaderContract
from tests.support.fixtures import NOTICE_LINES, make_notice_pdf

import docaudit
from docaudit.backends.vlm import DEFAULT_URL, VLM
from docaudit.pdf import PageView, load_pages, opened

pytestmark = [pytest.mark.slow, pytest.mark.integration]

URL = os.environ.get("DOCAUDIT_VLM_URL", DEFAULT_URL)


@pytest.fixture(scope="module")
def server() -> str:
    try:
        with urllib.request.urlopen(f"{URL}/health", timeout=5) as resp:
            if b"ok" not in resp.read():
                pytest.skip(f"llama-server em {URL} não está pronto")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        pytest.skip(f"sem llama-server em {URL}: {exc}")
    return URL


def test_reads_accented_portuguese(server: str) -> None:
    result = docaudit.process(
        make_notice_pdf(
            ["TERMO DE AUDIÊNCIA DE CONCILIAÇÃO Nº 3", "Requerente: José Conceição Araújo"]
        ),
        policy="all_strong",
        strong=VLM(server),
    )
    text = "\n".join(c.text for c in result.chunks)
    assert "CONCILIAÇÃO" in text
    assert "Conceição" in text
    assert result.spent.seconds_strong > 0


class TestVLMContract(ReaderContract):
    @pytest.fixture
    def reader(self, server: str):
        return VLM(server)


def test_layout_finds_the_notice_body_and_drops_nothing_of_it() -> None:
    pytest.importorskip("onnxruntime", reason="precisa do extra `layout`")
    from docaudit.backends.layout import PPDocLayout

    doc = make_notice_pdf()
    with opened(doc) as pdf:
        image = PageView(pdf, load_pages(doc)[0]).image(grayscale=False)
    regions = PPDocLayout().detect(image)
    assert regions, "um edital tem ao menos uma região de texto"
    assert all(r.label not in {"header", "footer", "seal"} for r in regions)
    assert len(regions) <= len(NOTICE_LINES), f"regiões demais: {regions}"
    assert {r.label for r in regions} == {"text"}
    tops = [r.bbox.y0 for r in regions]
    assert tops == sorted(tops), "a ordem de leitura desce a página"


def test_regions_reach_the_creditor_names(server: str) -> None:
    pytest.importorskip("onnxruntime", reason="precisa do extra `layout`")
    from docaudit.backends.layout import PPDocLayout

    result = docaudit.process(
        make_notice_pdf(),
        policy="all_strong",
        strong=VLM(server, layout=PPDocLayout()),
    )
    text = "\n".join(c.text for c in result.chunks).upper()
    assert "ANDRADE" in text
    assert all(c.bbox.area < 1.0 for c in result.chunks), "a caixa é a da região"
