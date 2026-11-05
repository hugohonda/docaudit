"""O que o arquivo diz de si: metadados, versão, gravações, assinaturas e as fontes da camada."""

from datetime import UTC, datetime, timedelta, timezone

from tests.support import make_pdf, make_scanned_pdf
from tests.support.fixtures import TEXT_CENTRAL

import docaudit
from docaudit import Document, DocumentFacts
from docaudit.pdf import _pdf_date, load_facts, load_pages

_INFO = {
    "Producer": "montador 1.0",
    "Creator": "editor",
    "Title": "Edital",
    "CreationDate": "D:20240315103000-03'00'",
    "ModDate": "D:20240316000000Z",
}


def test_a_bare_pdf_has_no_metadata_no_signature_and_one_save():
    facts = load_facts(make_pdf(TEXT_CENTRAL))
    assert isinstance(facts, DocumentFacts)
    assert (facts.producer, facts.creator, facts.title, facts.created_at) == (
        None,
        None,
        None,
        None,
    )
    assert (facts.pdf_version, facts.saves, facts.identifier_changed) == ("1.4", 1, None)
    assert (facts.tagged, facts.form, facts.restricted, facts.page_labels) == (
        False,
        "none",
        False,
        False,
    )
    assert facts.signatures == ()


def test_the_info_dictionary_and_the_dates_come_with_their_zone():
    facts = load_facts(make_pdf(TEXT_CENTRAL, info=_INFO))
    assert (facts.producer, facts.creator, facts.title) == ("montador 1.0", "editor", "Edital")
    assert facts.created_at == datetime(2024, 3, 15, 10, 30, tzinfo=timezone(timedelta(hours=-3)))
    assert facts.modified_at == datetime(2024, 3, 16, tzinfo=UTC)


def test_the_file_id_says_whether_the_file_was_rewritten():
    same = load_facts(make_pdf(TEXT_CENTRAL, ids=(b"a" * 16, b"a" * 16)))
    changed = load_facts(make_pdf(TEXT_CENTRAL, ids=(b"a" * 16, b"b" * 16)))
    assert (same.identifier_changed, changed.identifier_changed) == (False, True)


def test_an_incremental_update_counts_as_a_second_save():
    facts = load_facts(make_pdf(TEXT_CENTRAL, info=_INFO, incremental=True))
    assert facts.saves == 2
    assert facts.producer == "update", "o trailer novo aponta o `/Info` regravado"


def test_a_declared_signature_is_read_without_being_verified():
    pdf = make_pdf(TEXT_CENTRAL, signature=True)
    facts = load_facts(pdf)
    assert facts.form == "acroform"
    assert len(facts.signatures) == 1
    sig = facts.signatures[0]
    assert sig.sub_filter == "ETSI.CAdES.detached"
    assert sig.reason == "Juntada"
    assert sig.signed_at == datetime(2024, 3, 15, 10, 30, tzinfo=timezone(timedelta(hours=-3)))
    assert sig.covers_file, "o /ByteRange chega ao fim do arquivo"
    assert (
        not load_facts(make_pdf(TEXT_CENTRAL, signature=True, incremental=True))
        .signatures[0]
        .covers_file
    ), "gravado de novo depois de assinado"


def test_the_pdf_date_reads_every_form_and_refuses_a_broken_one():
    assert _pdf_date("D:20240315") == datetime(2024, 3, 15)
    assert _pdf_date("20240315103000") == datetime(2024, 3, 15, 10, 30)
    assert _pdf_date("D:20240315103000+05'30'") == datetime(
        2024, 3, 15, 10, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    assert _pdf_date("D:20241345") is None
    assert _pdf_date("") is None
    assert _pdf_date(None) is None


def test_the_hidden_fonts_name_who_wrote_the_layer_and_a_typeset_page_has_none():
    scanned = load_pages(make_scanned_pdf(["linha da camada"]))[0]
    typeset = load_pages(make_pdf(TEXT_CENTRAL))[0]
    assert scanned.hidden_fonts == ("Helvetica",)
    assert typeset.hidden_fonts == ()


def test_process_and_document_carry_the_facts_and_the_markdown_header_names_them():
    pdf = make_pdf(TEXT_CENTRAL, info=_INFO, signature=True)
    result = docaudit.process(pdf, cheap=["text_layer"])
    assert result.document is not None
    assert result.document.producer == "montador 1.0"
    header = result.to_markdown(annotated=True).splitlines()[0]
    assert header == "<!-- documento · PDF 1.4 · gravado por montador 1.0 · 1 assinatura(s) -->"
    assert "documento" not in result.to_markdown().splitlines()[0]
    with Document(pdf, cheap=["text_layer"]) as doc:
        assert doc.facts == result.document
        assert doc.read(policy="all_cheap").document == doc.facts
