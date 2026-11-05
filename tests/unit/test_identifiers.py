"""Os ids com dígito verificador que entram por escolha: PIS, título de eleitor, CNH e RENAVAM."""

import pytest
from tests.support.fixtures import make_page, make_pdf

import docaudit
from docaudit import EntityState
from docaudit.policies import (
    CNH,
    DEFAULT_ENTITIES,
    DEFAULT_SIGNALS,
    IDENTIFIERS,
    PIS,
    RENAVAM,
    VOTER_ID,
    EvidenceRouter,
    FailsCheck,
    entities_of,
    failures,
)
from docaudit.types import BBox, Chunk


def _line(page, y: float, text: str) -> Chunk:
    return Chunk.make(page, BBox(x0=0.1, y0=y, x1=0.9, y1=y + 0.02), "fake", text)


@pytest.mark.parametrize(
    ("check", "good", "bad"),
    [
        (PIS, "252.27986.42-9", "252.27986.42-8"),
        (PIS, "649.35981.46-9", "649.35981.4b-9"),
        (VOTER_ID, "7513 1377 2879", "7513 1377 2878"),
        (VOTER_ID, "6249 8494 2801", "6249 8494 28O1"),
        (CNH, "CNH 98765432100", "CNH 98765432101"),
        (CNH, "Registro nº 98765432100", "Registro nº 9876543210O"),
        (RENAVAM, "RENAVAM 86769597308", "RENAVAM 86769597309"),
        (RENAVAM, "RENAVAM: 00639884962", "RENAVAM: 0063988496Z"),
    ],
)
def test_each_identifier_confirms_a_true_value_and_fails_a_swapped_one(check, good, bad):
    assert failures(check, f"ver {good} e {bad}.") == 1
    assert failures(check, f"ver {good}.") == 0


def test_renavam_takes_only_eleven_digits_glued_to_its_label():
    page = make_page(0)
    line = _line(page, 0.1, "RENAVAM 639884962, RENAVAM 00639884962/2024, RENAVAM nº 00639884962.")
    found = entities_of([RENAVAM], page, [line])
    assert [(e.value, e.state) for e in found] == [("00639884962", EntityState.CONFIRMED)], (
        "nove dígitos não são RENAVAM, e o número colado a outro também não"
    )
    assert failures(RENAVAM, "RENAVAM/MF 00639884962 e RENAVAM consultado em 2024") == 0


def test_the_label_stays_out_of_the_value_and_a_bare_number_is_not_an_id():
    page = make_page(0)
    labeled = _line(page, 0.1, "PIS/PASEP: 25227986429 e Título de Eleitor nº 751313772879")
    with_label_in_form = _line(page, 0.2, "CNH 98765432100 e RENAVAM: 00639884962")
    bare = _line(page, 0.3, "protocolo 25227986429 e telefone 751313772879 e registro 1234")
    found = entities_of(list(IDENTIFIERS), page, [labeled, with_label_in_form, bare])
    assert [(e.kind, e.value, e.state) for e in found] == [
        ("PIS", "25227986429", EntityState.CONFIRMED),
        ("título de eleitor", "751313772879", EntityState.CONFIRMED),
        ("CNH", "98765432100", EntityState.CONFIRMED),
        ("RENAVAM", "00639884962", EntityState.CONFIRMED),
    ]


def test_the_thirteen_digit_voter_id_of_sao_paulo_enters_by_the_label():
    # Nove de sequência, UF 01, e os dois dígitos calculados sobre os oito primeiros.
    page = make_page(0)
    line = _line(page, 0.1, "Título de Eleitor 1234567890191 e Título de Eleitor 1234567890281")
    found = entities_of([VOTER_ID], page, [line])
    assert [(e.value, e.state) for e in found] == [
        ("1234567890191", EntityState.CONFIRMED),
        ("1234567890281", EntityState.FAILED),
    ], "treze dígitos valem só em São Paulo e Minas Gerais"
    assert VOTER_ID.is_valid("1234 5678 0191"), "o mesmo título com oito de sequência"


def test_the_identifiers_stay_out_of_the_defaults_and_enter_by_choice():
    assert not set(IDENTIFIERS) & set(DEFAULT_ENTITIES)
    assert not any(isinstance(s, FailsCheck) and s.check in IDENTIFIERS for s in DEFAULT_SIGNALS)
    policy = EvidenceRouter([*DEFAULT_SIGNALS, *map(FailsCheck, IDENTIFIERS)])
    assert [c.check.name for c in policy.checks[-4:]] == [
        "PIS",
        "título de eleitor",
        "CNH",
        "RENAVAM",
    ]


def test_process_reports_the_chosen_identifiers_with_the_line_they_came_from():
    pdf = make_pdf("BT /F1 12 Tf 72 700 Td (PIS 252.27986.42-9 RENAVAM 86769597308) Tj ET")
    result = docaudit.process(pdf, cheap=["text_layer"], entities=[*DEFAULT_ENTITIES, *IDENTIFIERS])
    kinds = {(e.kind, e.value, e.state) for e in result.entities}
    assert ("PIS", "252.27986.42-9", EntityState.CONFIRMED) in kinds
    assert ("RENAVAM", "86769597308", EntityState.CONFIRMED) in kinds
