"""Nenhuma página do pdfium escapa do lock.

O pdfium não é seguro para uso concorrente, e `PdfPage` tem finalizador: uma
página deixada para a coleta fecha de outra thread, fora do lock, e derruba o
processo. A regra é que toda página aberta é fechada explicitamente, com o lock
tomado nas duas pontas.

Este teste conta cargas e fechamentos em vez de tentar reproduzir a corrida: um
segfault não é uma falha de asserção, e um teste que depende dele só acusa o
problema às vezes.
"""

from __future__ import annotations

import pypdfium2 as pdfium
import pytest
from tests.support import make_scanned_pdf

from docaudit import pdf as pdf_mod


@pytest.fixture
def counting(monkeypatch):
    """Instrumenta carga e fechamento de página, exigindo o lock em ambos."""
    counts = {"loaded": 0, "closed": 0}
    real_get_page = pdfium.PdfDocument.get_page

    def get_page(self, index):
        assert pdf_mod._PDFIUM.locked(), "página carregada sem o lock"
        page = real_get_page(self, index)
        counts["loaded"] += 1
        real_close = page.close

        def close(*args, **kwargs):
            assert pdf_mod._PDFIUM.locked(), "página fechada sem o lock"
            counts["closed"] += 1
            return real_close(*args, **kwargs)

        page.close = close
        return page

    monkeypatch.setattr(pdfium.PdfDocument, "get_page", get_page)
    return counts


def test_every_page_read_closes_under_the_lock(counting):
    document = make_scanned_pdf(["LINHA UM", "LINHA DOIS"])
    with pdf_mod.opened(document) as handle:
        pdf_mod.text_lines_of(handle, 0)
        pdf_mod.render_of(handle, 0, dpi=72)
        pdf_mod.pages_of(handle, "doc", dpi=72)

    assert counting["loaded"] > 0
    assert counting["closed"] == counting["loaded"]


def test_filtered_pages_are_never_loaded(counting):
    document = make_scanned_pdf()
    with pdf_mod.opened(document) as handle:
        pdf_mod.pages_of(handle, "doc", dpi=72, only=set())

    # `only` precisa evitar a carga, não só a classificação: num documento de mil
    # páginas, carregar todas para descartar 998 é o custo que `pages=` promete
    # não cobrar.
    assert counting["loaded"] == 0
