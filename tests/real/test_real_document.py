"""O pipeline contra um PDF público de verdade.

Tudo o mais na suíte roda sobre documentos que este repositório fabrica, e um
fixture sintético concorda com quem o escreveu por construção. Este é um termo
de referência de digitalização publicado por tribunal, o mesmo gênero de
documento que a biblioteca lê.

Marcados `real` e `slow`: dependem de rede. A CI roda `-m "not slow"`.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

import docaudit
from docaudit.pdf import load_pages, opened, text_lines_of
from docaudit.types import Substrate

pytestmark = [pytest.mark.real, pytest.mark.slow]


@pytest.fixture(scope="module")
def pages_list(real_document):
    return load_pages(real_document)


def test_is_born_digital_throughout(pages_list) -> None:
    """Nenhuma página é escaneada, e o classificador não pode inventar que são.

    É o lado negativo que importa: marcar estas como `SEARCHABLE_SCAN` mandaria
    OCR rodar sobre texto vetorial exato.
    """
    assert len(pages_list) > 1
    assert all(p.substrate is Substrate.BORN_DIGITAL for p in pages_list)


def test_body_text_is_drawn_visible(pages_list) -> None:
    """Num ato normativo nativo digital, o texto foi composto, não reconhecido.

    É a evidência direta que separa as duas primeiras classes: um motor de OCR
    desenharia o texto em modo invisível sobre a imagem. Aqui não há nenhum.
    """
    invisible_total = sum(p.substrate_evidence["invisible_text"] for p in pages_list)
    visible_total = sum(p.substrate_evidence["visible_text"] for p in pages_list)
    assert visible_total > 0
    assert invisible_total == 0, "um documento composto não deveria ter text_value invisível"


def test_text_boxes_are_real_and_small(real_document) -> None:
    """A caixa de cada trecho cobre o trecho, não a página.

    Sem supor o que há numa página específica: a primeira deste documento é uma
    capa com quatro linhas. A invariante é sobre a forma das caixas, não sobre a
    densidade do texto.
    """
    with opened(real_document) as pdf:
        all_lines = [r for i in range(min(len(pdf), 5)) for r in text_lines_of(pdf, i)]

    assert all_lines, "nenhum retângulo de text_value num PDF nativo digital"
    assert all(0.0 <= b.x0 <= b.x1 <= 1.0 and 0.0 <= b.y0 <= b.y1 <= 1.0 for b, _, _ in all_lines)
    assert all(t.strip() for _, t, _ in all_lines), (
        "retângulo sem text_value não deveria ser emitido"
    )

    mean = sum(b.area for b, _, _ in all_lines) / len(all_lines)
    assert mean < 0.05, f"área média {mean:.4f}: as caixas parecem de página inteira"


def test_reads_the_document_end_to_end(real_document) -> None:
    """Pipeline completo: o texto sai legível, com proveniência, sem tier caro."""
    result = docaudit.process(real_document, policy="all_cheap", cheap=["text_layer"])

    text_value = " ".join(c.text for c in result.chunks).upper()
    assert "DIGITALIZA" in text_value, "não achou o assunto do documento no text_value lido"
    assert result.spent.pages_strong == 0.0
    assert {c.source for c in result.chunks} == {"text_layer"}
    assert all(c.reading_order is not None for c in result.chunks)


def test_reading_order_descends_the_page(real_document) -> None:
    """A ordem que o pdfium devolve acompanha o fluxo da página."""
    result = docaudit.process(real_document, policy="all_cheap", cheap=["text_layer"])
    de_uma_pagina = [c for c in result.chunks if c.page == 1]
    ordered = sorted(de_uma_pagina, key=lambda c: c.reading_order or 0)

    # Não é estritamente monotônico, e não deve ser: trechos da mesma linha
    # compartilham o topo, e uma nota de rodapé ou segunda coluna sobe de novo.
    # A tolerância é a altura de uma linha de corpo numa A4.
    altura_de_linha = 0.01
    fracao_minima_descendo = 0.8

    descending = sum(1 for a, b in pairwise(ordered) if b.bbox.y0 >= a.bbox.y0 - altura_de_linha)
    assert descending / max(len(ordered) - 1, 1) > fracao_minima_descendo
