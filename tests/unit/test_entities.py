"""As entidades do resultado: cada valor com forma e regra, com estado e linha de origem."""

import re

from tests.support.fixtures import make_page, make_pdf, make_scanned_pdf

import docaudit
from docaudit import Document, EntityState
from docaudit.policies import (
    AMOUNT_BRL,
    AMOUNT_IN_WORDS,
    CNJ,
    CNPJ,
    CPF,
    DATE_DMY,
    DATE_VERBOSE,
    DATE_WEEKDAY,
    DEFAULT_ENTITIES,
    DEFAULT_SIGNALS,
    FOLHA,
    Check,
    EvidenceRouter,
    FailsCheck,
    GarbledText,
    entities_of,
)
from docaudit.process import _entity_checks
from docaudit.types import BBox, Chunk, Substrate


def _line(page, y: float, text: str, source: str = "fake") -> Chunk:
    return Chunk.make(page, BBox(x0=0.1, y0=y, x1=0.9, y1=y + 0.02), source, text)


def test_states_follow_the_rule_and_its_redundancy():
    page = make_page(0, substrate=Substrate.BORN_DIGITAL)
    lines = [
        _line(page, 0.1, "CPF 529.982.247-25 e CPF 529.982.247-26"),
        _line(page, 0.2, "Total R$ 1.284.350,00 em 29/02/2013 e 31/01/2024"),
    ]
    found = entities_of(DEFAULT_ENTITIES, page, lines)
    assert [(e.kind, e.value, e.state) for e in found] == [
        ("CPF", "529.982.247-25", EntityState.CONFIRMED),
        ("CPF", "529.982.247-26", EntityState.FAILED),
        ("valor em reais", "R$ 1.284.350,00", EntityState.WELL_FORMED),
        ("data", "29/02/2013", EntityState.FAILED),
        ("data", "31/01/2024", EntityState.WELL_FORMED),
    ]
    assert all(e.page == 0 for e in found)
    assert found[0].chunk_ids == (lines[0].id,)
    assert found[0].bbox == lines[0].bbox


def test_a_value_split_across_lines_points_to_both_lines():
    page = make_page(0)
    lines = [_line(page, 0.1, "Valor devido: R$"), _line(page, 0.3, "4.000,00 (quatro mil reais)")]
    (amount,) = entities_of([AMOUNT_BRL], page, lines)
    assert amount.value == "R$ 4.000,00"
    assert amount.chunk_ids == (lines[0].id, lines[1].id)
    assert amount.bbox == BBox(x0=0.1, y0=0.1, x1=0.9, y1=0.32)


def test_rs_read_in_place_of_the_real_sign_is_an_amount_only_before_a_well_written_number():
    """O leitor de pixels lê o cifrão como `S`; a sigla do estado não vira valor."""
    page = make_page(0)
    lines = [
        _line(page, 0.1, "Total RS 1.234,56 e RS"),
        _line(page, 0.2, "78,90"),
        _line(page, 0.3, "Porto Alegre - RS, 12 de março"),
    ]
    found = entities_of([AMOUNT_BRL], page, lines)
    assert [(e.value, e.state) for e in found] == [
        ("RS 1.234,56", EntityState.WELL_FORMED),
        ("RS 78,90", EntityState.WELL_FORMED),
    ]


def test_amount_in_words_confirms_or_fails_the_figure():
    page = make_page(0)
    right = _line(page, 0.1, "R$ 214.000,00 (duzentos e quatorze mil reais)")
    wrong = _line(page, 0.2, "R$ 215.000,00 (duzentos e quatorze mil reais)")
    found = entities_of([AMOUNT_IN_WORDS], page, [right, wrong])
    assert [e.state for e in found] == [EntityState.CONFIRMED, EntityState.FAILED]


def test_default_entities_are_the_policy_checks_and_then_the_defaults():
    pis = Check("PIS", re.compile(r"\d{3}\.\d{5}\.\d{2}-\d"), lambda _: True)
    policy = EvidenceRouter([*DEFAULT_SIGNALS, FailsCheck(pis)])
    names = [c.name for c in _entity_checks(policy, None)]
    assert names == [
        "CPF",
        "CNPJ",
        "CNJ",
        "valor em reais",
        "valor em moeda anterior ao real",
        "PIS",
        "data",
        "data com dia da semana",
        "data por extenso",
        "folha",
        "chave de acesso",
        "linha digitável de boleto",
        "código de arrecadação",
    ]
    assert [c.name for c in _entity_checks(policy, [DATE_DMY])] == ["data"]


def test_process_reports_entities_of_the_final_text_with_refs():
    doc = make_pdf(
        "BT /F1 12 Tf 70 700 Td (Processo 9001087-60.2022.8.26.0390) Tj ET "
        "BT /F1 12 Tf 70 680 Td (Reu: CPF 529.982.247-26, em 10/03/2024) Tj ET"
    )
    result = docaudit.process(doc, cheap=["text_layer"])
    assert [(e.kind, e.state) for e in result.entities] == [
        ("CNJ", EntityState.CONFIRMED),
        ("CPF", EntityState.FAILED),
        ("data", EntityState.WELL_FORMED),
    ]
    refs = result.refs()
    assert list(refs) == ["p0:0", "p0:1"]
    assert refs["p0:1"].text.startswith("Reu")
    text = result.to_markdown(annotated=True)
    assert "[p0:0] Processo 9001087-60.2022.8.26.0390" in text
    assert "<!-- decisão: política all_cheap -->" in text
    assert "- CPF: 529.982.247-26 · failed (impresso assim: text_layer) · p0:1" in text
    assert result.entities[1].printed == "text_layer", "camada composta: o erro é do documento"
    assert "- data: 10/03/2024 · well_formed · p0:1" in text
    assert "[p0" not in result.to_markdown()


def test_cited_confers_a_value_in_the_line_without_spaces_or_typographic_hyphens():
    doc = make_pdf(
        "BT /F1 12 Tf 70 700 Td (Processo 9001087-60.2022.8.26.0390) Tj ET "
        "BT /F1 12 Tf 70 680 Td (Reu: CPF 529.982.247-26) Tj ET"
    )
    result = docaudit.process(doc, cheap=["text_layer"])
    line = result.refs()["p0:1"]
    assert result.cited("p0:1", "529.982.247\u201026") == [line], "hífen tipográfico"
    assert result.cited("p0:1", "529 982 247-26") == [line], "a pontuação não conta"
    assert result.cited("p0:1", "529.982.247 - 26") == [line], "o espaço não conta"
    assert result.cited("p0:1", "529.982.247-27") == [], "um dígito conta"
    assert result.cited("p0:0", "529.982.247-26") == [], "outra linha"
    assert result.cited("p0:9", "529.982.247-26") == [], "referência inexistente"
    assert result.cited("p0:1", " ") == [], "valor vazio"


def test_cited_takes_pieces_around_ellipses_in_the_cited_order_and_the_entity_in_them():
    doc = make_pdf(
        'BT /F1 12 Tf 70 700 Td (A empresa "ALFA LTDA", na condicao de CEDENTE, '
        "cede a BETA S.A.) Tj ET"
    )
    result = docaudit.process(doc, cheap=["text_layer"])
    line = result.refs()["p0:0"]
    assert result.cited("p0:0", "ALFA LTDA [...] CEDENTE ... BETA") == [line], "pedaços na ordem"
    assert result.cited("p0:0", "BETA \u2026 CEDENTE") == [], "pedaços fora de ordem"
    assert result.cited("p0:0", "\u201cALFA LTDA\u201d") == [line], "aspas tipográficas"
    assert result.cited("p0:0", "ALFA ... ") == [line], "reticência no fim, sem pedaço vazio"
    assert result.cited("p0:0", "...") == [], "só reticências"
    assert result.cited("p0:0", "na condicao de CEDENTE", entity="ALFA LTDA") == [], (
        "a entidade tem de estar na citação, não só na linha"
    )
    assert result.cited("p0:0", "ALFA LTDA ... CEDENTE", entity="ALFA LTDA") == [line]
    assert result.cited("p0:0", "ALFA LTDA ... CEDENTE", entity="") == [], "entidade vazia"


def test_annotated_markdown_marks_the_list_line_and_the_layout_blocks():
    doc = make_pdf(
        "BT /F1 12 Tf 70 700 Td (Fornecedores: 11.222.333/0001-81 e 44.555.666/0001-09) Tj ET "
        "BT /F1 12 Tf 70 680 Td (Contratante: CNPJ 16.448.870/0001-68) Tj ET"
    )
    result = docaudit.process(doc, cheap=["text_layer"])
    text = result.to_markdown(annotated=True)
    assert "- linhas de lista: p0:0" in text, "dois CNPJ na mesma linha"
    assert "p0:1" not in text.split("- linhas de lista: ")[1].splitlines()[0]
    assert "- blocos:" not in text, "sem detector de layout, sem blocos"


def test_cited_takes_a_value_split_between_two_lines_in_the_cited_order():
    doc = make_pdf(
        "BT /F1 12 Tf 70 700 Td (Total: R$) Tj ET BT /F1 12 Tf 70 680 Td (4.000,00 reais) Tj ET"
    )
    result = docaudit.process(doc, cheap=["text_layer"])
    both = [result.refs()["p0:0"], result.refs()["p0:1"]]
    assert result.cited(["p0:0", "p0:1"], "R$ 4.000,00") == both
    assert result.cited(["p0:1", "p0:0"], "R$ 4.000,00") == [], "na ordem citada"
    assert result.cited("p0:1", "R$ 4.000,00") == [], "uma linha só não tem o valor"
    assert result.cited([], "R$ 4.000,00") == []


def test_entities_argument_replaces_the_defaults():
    doc = make_pdf("BT /F1 12 Tf 70 700 Td (CPF 529.982.247-25 em 10/03/2024) Tj ET")
    result = docaudit.process(doc, cheap=["text_layer"], entities=[CNJ])
    assert result.entities == ()
    result = docaudit.process(doc, cheap=["text_layer"], entities=[DATE_DMY])
    assert [e.kind for e in result.entities] == ["data"]


def test_a_date_glued_to_an_id_is_found_and_one_inside_a_number_is_not():
    page = make_page(0)
    line = _line(page, 0.5, "529.982.247-2511/12/1972 e 1211/12/1972")
    found = entities_of([CPF, DATE_DMY], page, [line])
    assert [(e.kind, e.value) for e in found] == [
        ("CPF", "529.982.247-25"),
        ("data", "11/12/1972"),
    ]


def test_a_date_with_its_weekday_is_confirmed_when_the_calendar_agrees():
    page = make_page(0)
    header = _line(page, 0.03, "D.O.M. ANO X Nº 2343, Quarta-feira, 05 de Janeiro de 2022")
    numeric = _line(page, 0.1, "São Paulo, segunda-feira, 10/03/2025.")
    wrong = _line(page, 0.2, "TERÇA-FEIRA, 05 de MARÇO de 2022")
    split = _line(page, 0.3, "Sertãozinho, sexta-feira,")
    split_date = _line(page, 0.32, "1º de julho de 2022")
    found = entities_of([DATE_WEEKDAY], page, [header, numeric, wrong, split, split_date])
    assert [(e.value, e.state) for e in found] == [
        ("Quarta-feira, 05 de Janeiro de 2022", EntityState.CONFIRMED),
        ("segunda-feira, 10/03/2025", EntityState.CONFIRMED),
        ("TERÇA-FEIRA, 05 de MARÇO de 2022", EntityState.FAILED),
        ("sexta-feira, 1º de julho de 2022", EntityState.CONFIRMED),
    ]
    assert found[3].chunk_ids == (split.id, split_date.id), "o dia numa linha, a data na outra"


def test_a_date_in_words_is_well_formed_when_it_exists_and_a_word_that_is_not_a_month_is_nothing():
    page = make_page(0)
    closing = _line(page, 0.1, "São Paulo, 1º de março de 2024.")
    shouted = _line(page, 0.2, "em 15 de MARCO de 2024, e não em 30 de FEVEREIRO de 2023")
    not_a_month = _line(page, 0.3, "10 de xpto de 2024")
    split = _line(page, 0.4, "Sertãozinho, 31 de julho")
    split_year = _line(page, 0.42, "de 2022")
    found = entities_of([DATE_VERBOSE], page, [closing, shouted, not_a_month, split, split_year])
    assert [(e.value, e.state) for e in found] == [
        ("1º de março de 2024", EntityState.WELL_FORMED),
        ("15 de MARCO de 2024", EntityState.WELL_FORMED),
        ("30 de FEVEREIRO de 2023", EntityState.FAILED),
        ("31 de julho de 2022", EntityState.WELL_FORMED),
    ]
    assert found[3].chunk_ids == (split.id, split_year.id), "o ano na linha seguinte"
    assert DATE_VERBOSE in DEFAULT_ENTITIES
    assert all(
        not isinstance(s, FailsCheck) or s.check is not DATE_VERBOSE for s in DEFAULT_SIGNALS
    )


def test_a_label_admits_its_id_in_any_punctuation_and_the_check_digit_decides():
    page = make_page(0)
    signed = _line(page, 0.1, "Signatário(a): FULANO DE TAL CPF: 22279745836")
    spaced = _line(page, 0.2, "executados CPF 030 058 098-38 e CNPJ : 52849569/0001-20")
    standard = _line(page, 0.3, "Requerente CPF 529.982.247-25, telefone 11999998888")
    misread = _line(page, 0.4, "CPF/MF: 05 5.30 4.5 18/82")
    found = entities_of([CPF, CNPJ], page, [signed, spaced, standard, misread])
    assert [(e.kind, e.value, e.state) for e in found] == [
        ("CPF", "22279745836", EntityState.CONFIRMED),
        ("CPF", "030 058 098-38", EntityState.CONFIRMED),
        ("CNPJ", "52849569/0001-20", EntityState.CONFIRMED),
        ("CPF", "529.982.247-25", EntityState.CONFIRMED),
        ("CPF", "05 5.30 4.5 18/82", EntityState.FAILED),
    ], "o padrão vale como antes, e o telefone sem rótulo não é id"


def test_a_label_admitted_id_that_fails_does_not_route_the_page():
    page = make_page(0)
    misread = _line(page, 0.4, "CPF/MF: 05 5.30 4.5 18/82")
    assert FailsCheck(CPF).failing(page, [misread]) == [], "o rótulo só extrai"


def test_the_folha_stamp_and_a_cited_folha_are_entities_and_a_range_is_not():
    page = make_page(0)
    stamp = _line(page, 0.03, "fls. 730")
    body = _line(page, 0.5, "intimada (fls. 08/10); a decisão de fl. 16 e o ofício de fls. 5.662.")
    found = entities_of([FOLHA], page, [stamp, body])
    assert [(e.value, e.state, e.chunk_ids) for e in found] == [
        ("fls. 730", EntityState.WELL_FORMED, (stamp.id,)),
        ("fl. 16", EntityState.WELL_FORMED, (body.id,)),
        ("fls. 5.662", EntityState.WELL_FORMED, (body.id,)),
    ]


def test_a_four_digit_folha_without_a_dot_and_the_colon_form_are_folhas():
    page = make_page(0)
    stamp = _line(page, 0.03, "fls. 1002")
    old = _line(page, 0.06, "fls: 340 e fls:5846")
    found = entities_of([FOLHA], page, [stamp, old])
    assert [e.value for e in found] == ["fls. 1002", "fls: 340", "fls:5846"]


def test_the_band_code_is_not_a_folha_and_the_verso_and_a_glued_band_are():
    page = make_page(0)
    band = _line(page, 0.9, "informe o processo 1000000-00.2024.8.26.0100 e código fL8lW7AI.")
    glued = _line(page, 0.03, "fls. 149Este documento é cópia do original")
    verso = _line(page, 0.5, "às fls. 9494vº e fls. 12 vide")
    found = entities_of([FOLHA], page, [band, glued, verso])
    assert [e.value for e in found] == ["fls. 149", "fls. 9494vº", "fls. 12"]


def test_garbled_text_points_to_the_line_and_its_code_points():
    page = make_page(0)
    clean = _line(page, 0.1, "texto limpo")
    broken = _line(page, 0.2, "nome � cargo")
    assert GarbledText().failing(page, [clean, broken]) == [("U+F0B7, U+FFFD", broken)]


def test_document_doubts_include_garbled_lines_and_read_takes_entities():
    doc = make_scanned_pdf(["CPF 529.982.247-27", "Item lido"])
    with Document(doc, cheap=["text_layer"], trust_layer="always") as session:
        result = session.read(entities=[CPF])
        assert [(e.kind, e.state) for e in result.entities] == [("CPF", EntityState.FAILED)]
        # O PDF mínimo não grava U+FFFD; a linha mal decodificada entra no resultado.
        broken = result.chunks[1].model_copy(update={"text": "Item � lido"})
        result = result.model_copy(update={"chunks": (result.chunks[0], broken)})
        doubts = session.doubts(result)
        # Na ordem dos sinais da política: o texto mal decodificado vem antes.
        assert [(d.check, d.value) for d in doubts] == [
            ("texto mal decodificado", "U+FFFD"),
            ("CPF", "529.982.247-27"),
        ]
        assert doubts[0].chunk.text == "Item � lido"
