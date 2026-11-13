"""Ponta a ponta de `process` com backends falsos.

Valida o que a biblioteca promete sem depender de nenhum peso de modelo: que
páginas nativas digitais saem da camada de texto sem tocar no OCR, que o
orçamento é respeitado, que o cache evita a segunda chamada e que o portão de
anonimização barra um backend externo.
"""

import re
import time
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Literal

import pytest
from tests.support import FakeVLM, ReaderContract, make_page, make_pdf, make_scanned_pdf
from tests.support.fixtures import EMPTY_PAGE, TEXT_CENTRAL

from docaudit import Budget, mark_furniture, process
from docaudit.backends.textlayer import TextLayerReader
from docaudit.cache import ModelCallCache
from docaudit.pdf import PageView, RegionView, drawn_lines_of, load_pages, opened, pages_of
from docaudit.policies import CPF, ESAJ_STAMP, Check, StampFormat
from docaudit.process import (
    RASTER_MARGIN,
    _in_place_of_pixels,
    _read_cascade,
    folhas_of,
    stamps_of,
)
from docaudit.types import BBox, Chunk, EntityState, ExternalBackendError, Region, Tier


def _is_blank(image: bytes) -> bool:
    """Um motor de verdade não inventa texto numa página branca; o fake também não."""
    if not image:
        return True
    import io

    from PIL import Image

    lo, hi = Image.open(io.BytesIO(image)).convert("L").getextrema()
    return lo == hi


class FakeOCR:
    """Devolve uma caixa fixa com texto previsível, e conta as chamadas."""

    name = "fake-ocr"
    external = False
    output_version = "v1"

    def __init__(self):
        self.calls = 0

    def read(self, view):
        self.calls += 1
        # A imagem primeiro: é ela que carimba o hash na página.
        image = view.image()
        page = view.page
        bbox = BBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
        text = "" if _is_blank(image) else f"ocr pagina {page.index}"
        return [
            Chunk(
                id=Chunk.make_id(Chunk.key_of(page), bbox, self.name, text, page=page.index),
                page=page.index,
                bbox=bbox,
                text=text,
                source=self.name,
                confidence=0.8,
                reading_order=0,
            )
        ]


@pytest.fixture
def scanned_doc():
    """Cinco páginas sem texto: o caso que o padrão just-in-time não cobre."""
    return make_pdf(*[EMPTY_PAGE] * 5)


def test_text_layer_wins_the_cascade_on_born_digital():
    """Cascata declarativa: a camada de texto aceita a página e o OCR nem é chamado."""
    ocr = FakeOCR()
    result = process(make_pdf(TEXT_CENTRAL), policy="all_cheap", cheap=["text_layer", ocr])
    assert ocr.calls == 0
    assert {c.source for c in result.chunks} == {"text_layer"}
    assert "EDITAL" in " ".join(c.text for c in result.chunks)


def test_text_layer_declines_a_scan_and_the_cascade_falls_through(scanned_doc):
    """Num escaneado a camada de texto recusa, e o próximo leitor assume."""
    ocr = FakeOCR()
    result = process(scanned_doc, policy="all_cheap", cheap=["text_layer", ocr])
    assert ocr.calls == 5
    assert {c.source for c in result.chunks} == {"fake-ocr"}


def test_cascade_order_is_the_callers():
    """Invertida a ordem, o OCR vence mesmo numa página nativa digital."""
    ocr = FakeOCR()
    result = process(make_pdf(TEXT_CENTRAL), policy="all_cheap", cheap=[ocr, "text_layer"])
    assert ocr.calls == 1
    assert {c.source for c in result.chunks} == {"fake-ocr"}


class _FailsOnPage(FakeOCR):
    """Um leitor cujo motor falha numa página: o erro nativo vira `RuntimeError`."""

    name = "falha"

    def __init__(self, page: int | None):
        """`page` é a página que falha; `None`, todas, como um motor quebrado."""
        super().__init__()
        self.page = page

    def read(self, view):
        if self.page in (None, view.page.index):
            raise RuntimeError("motor caiu")
        return super().read(view)


def test_a_reader_failing_on_one_page_hands_it_to_the_next(scanned_doc):
    """A falha fica na página: o seguinte da cascata a lê, o gasto a conta e a decisão a diz."""
    backup = FakeOCR()
    with pytest.warns(RuntimeWarning, match="falha falhou na página 2"):
        result = process(scanned_doc, policy="all_cheap", cheap=[_FailsOnPage(2), backup])
    assert backup.calls == 1
    assert {c.page for c in result.chunks if c.source == "fake-ocr"} == {2}
    assert result.spent.pages_cheap_failed == 1.0
    failures = {d.page: d.failures for d in result.decisions}
    assert failures[2] == ("falha: motor caiu",)
    assert all(not f for page, f in failures.items() if page != 2)


@pytest.mark.parametrize(("page", "expected"), [(2, [2]), (None, [0, 1, 2, 3, 4])])
def test_a_reader_that_fails_keeps_the_read_and_marks_the_pages(scanned_doc, page, expected):
    """A falha não derruba o documento: a decisão diz cada página que ficou sem leitor."""
    with pytest.warns(RuntimeWarning, match="falha falhou na página"):
        result = process(scanned_doc, policy="all_cheap", cheap=[_FailsOnPage(page)])
    assert [d.page for d in result.decisions if d.incomplete] == expected


def test_a_failure_another_reader_covered_is_not_incomplete(scanned_doc):
    """O seguinte da cascata leu: a nota fica em `failures`, e a página está inteira."""
    with pytest.warns(RuntimeWarning):
        result = process(scanned_doc, policy="all_cheap", cheap=[_FailsOnPage(2), FakeOCR()])
    assert not any(d.incomplete for d in result.decisions)
    assert next(d for d in result.decisions if d.page == 2).failures


def test_a_blank_page_nobody_failed_on_is_not_incomplete(scanned_doc):
    """Página que o leitor leu e achou vazia é uma leitura, e não uma falha."""

    result = process(scanned_doc, policy="all_cheap", cheap=[_Says("vazio", {})])
    assert not any(d.incomplete for d in result.decisions)


def test_a_layer_line_does_not_hide_a_reader_that_failed_on_the_raster():
    """A tarja da camada não faz a página parecer lida: o corpo ficou sem leitor."""
    doc = make_scanned_pdf(["Num. 41560374 - Pag. 2"], render_mode=0, text_y=30)
    with pytest.warns(RuntimeWarning, match="falha falhou"):
        result = process(doc, policy="all_cheap", cheap=["text_layer", _FailsOnPage(None)])
    assert [c.source for c in result.chunks] == ["text_layer"]
    assert result.decisions[0].incomplete


def test_a_costly_reader_failing_keeps_the_cheap_read_whole():
    """A leitura barata ficou inteira: a falha do leitor caro não a torna incompleta."""
    doc = make_scanned_pdf(["CPF 529.982.247-27"])

    class Broken(FakeVLM):
        def read(self, view):
            raise RuntimeError("servidor caiu")

    with pytest.warns(RuntimeWarning):
        result = process(
            doc, policy="evidence", cheap=["text_layer"], strong=Broken(), trust_layer="always"
        )
    assert result.chunks
    assert not result.decisions[0].incomplete
    assert result.decisions[0].failures


def test_read_by_says_who_read_a_page_the_substrate_calls_digital():
    """A tarja vem da camada e o corpo dos pixels: a classe da página não diz isso."""
    doc = make_scanned_pdf(["Num. 41560374 - Pag. 2"], render_mode=0, text_y=30)
    result = process(doc, cheap=["text_layer", FakeOCR()])
    assert result.read_by() == {0: ("fake-ocr", "text_layer")}


def test_read_by_of_a_page_nobody_read_is_empty(scanned_doc):
    result = process(scanned_doc, policy="all_cheap", cheap=[_Says("vazio", {})])
    assert set(result.read_by().values()) == {()}


def test_verification_counts_each_check_by_state_and_the_printed_errors():
    """O CPF que outra família lê igual falha e conta em `printed`; o válido só no estado."""
    doc = make_scanned_pdf(["CPF 529.982.247-27", "CPF 529.982.247-25"])
    result = process(
        doc,
        policy="evidence",
        cheap=["text_layer"],
        confirm=FakeVLM(text="CPF 529.982.247-27 CPF 529.982.247-25"),
        trust_layer="always",
    )
    assert result.verification() == {0: {"CPF": {"failed": 1, "printed": 1, "confirmed": 1}}}


def test_verification_leaves_out_a_page_without_values(scanned_doc):
    assert process(scanned_doc, policy="all_cheap", cheap=[FakeOCR()]).verification() == {}


def test_scanned_pages_go_through_the_cheap_ocr(scanned_doc):
    ocr = FakeOCR()
    process(scanned_doc, policy="all_cheap", cheap=[ocr])
    assert ocr.calls == 5


def test_budget_caps_escalation(scanned_doc):
    """Cinco páginas em branco voltam vazias do OCR; o orçamento deixa escalar duas."""
    vlm = FakeVLM()
    result = process(
        scanned_doc,
        policy="evidence",
        budget=Budget(max_strong_fraction=0.4),
        cheap=[FakeOCR()],
        strong=vlm,
    )
    assert vlm.calls == 2
    assert result.spent.pages_strong == 2.0
    assert result.spent.pages_cheap == 5.0, "a política precisa da leitura barata de todas"
    assert sum(d.tier is Tier.STRONG for d in result.decisions) == 2


def test_without_a_vlm_nothing_escalates(scanned_doc):
    result = process(scanned_doc, policy="all_strong", cheap=[FakeOCR()])
    assert result.spent.pages_strong == 0.0
    assert all(c.source == "fake-ocr" for c in result.chunks)


def test_cache_prevents_the_second_call(tmp_path):
    doc = make_pdf(*[f"BT /F1 24 Tf 100 400 Td (pagina {i}) Tj ET" for i in range(5)])
    vlm = FakeVLM()
    cache = ModelCallCache(tmp_path / "c.sqlite")
    kwargs = {"policy": "all_strong", "cheap": [FakeOCR()], "strong": vlm, "cache": cache}
    first = process(doc, **kwargs)
    assert vlm.calls == 5
    second = process(doc, **kwargs)
    assert vlm.calls == 5, "a segunda passada tinha de sair toda do cache"
    assert [c.text for c in first.chunks] == [c.text for c in second.chunks]
    cache.close()


def test_cache_key_is_per_document_page(scanned_doc, tmp_path):
    """Cinco páginas de bytes idênticos são cinco leituras, e cinco entradas.

    A chave identifica a página pelo documento e pelo índice, não pelos pixels,
    para que consultar o cache não custe renderizar. O que se perde é partilhar
    a entrada entre páginas idênticas, raras num auto.
    """
    vlm = FakeVLM()
    cache = ModelCallCache(tmp_path / "c.sqlite")
    result = process(scanned_doc, policy="all_strong", cheap=[FakeOCR()], strong=vlm, cache=cache)
    assert vlm.calls == 5
    assert len(cache) == 5
    assert [c.page for c in result.chunks] == [0, 1, 2, 3, 4]
    assert len({c.id for c in result.chunks}) == 5
    cache.close()


def test_cache_serves_the_cheap_tier_too(scanned_doc, tmp_path):
    """OCR barato de mil páginas é caro de repetir: a segunda passada não o chama."""
    ocr = FakeOCR()
    cache = ModelCallCache(tmp_path / "c.sqlite")
    first = process(scanned_doc, cheap=[ocr], cache=cache)
    assert ocr.calls == 5
    assert first.spent.pages_cheap_cached == 0.0
    second = process(scanned_doc, cheap=[ocr], cache=cache)
    assert ocr.calls == 5
    assert second.spent.pages_cheap_cached == 5.0
    assert [c.id for c in first.chunks] == [c.id for c in second.chunks]
    cache.close()


def test_result_carries_the_library_version(scanned_doc):
    result = process(scanned_doc, policy="all_cheap", cheap=[FakeOCR()])
    assert result.library_version


def test_the_run_names_every_reader_that_read_a_line_with_its_version(scanned_doc):
    """Cada `Chunk.source` é chave de `run.versions`, e os argumentos estão no registro."""
    cheap = _Says("cheap", {0: "CPF 529.982.247-26", 1: "CPF 529.982.247-26", 2: "limpo"})
    other = _Says("other", {0: "CPF 529.982.247-27", 1: "CPF 529.982.247-25"})
    vlm = FakeVLM()
    result = process(
        scanned_doc,
        policy="evidence",
        budget=Budget(max_strong_pages=3),
        cheap=[cheap],
        confirm=other,
        strong=vlm,
        pages={0, 1, 2},
    )
    run = result.run
    assert run is not None
    sources = {c.source for c in result.chunks} | {o.reading.source for o in result.others}
    assert sources == {"cheap", "other", "fake-vlm"}
    assert run.versions == {
        "cheap": "v1",
        "other": "v1",
        "fake-vlm": vlm.output_version,
    }
    assert (run.policy, run.cheap, run.confirm, run.strong) == (
        "evidence",
        ("cheap",),
        "other",
        "fake-vlm",
    )
    assert run.budget == Budget(max_strong_pages=3)
    assert (run.reread, run.trust_layer, run.dpi) == ("page", "visible", None)
    assert "CPF" in run.entities
    assert run.started_at.tzinfo is not None
    again = type(result).model_validate_json(result.model_dump_json())
    assert again.run == run


def test_a_reader_that_read_nothing_has_no_version_in_the_run(scanned_doc):
    """A versão de um leitor caro nunca chamado não é pedida: pode custar uma consulta."""

    class _NoVersion(FakeVLM):
        @property
        def output_version(self):
            raise AssertionError("versão pedida sem leitura")

    result = process(scanned_doc, policy="all_cheap", cheap=[FakeOCR()], strong=_NoVersion())
    assert result.run is not None
    assert result.run.versions == {"fake-ocr": "v1"}
    assert result.run.strong == "fake-vlm"


def test_a_result_saved_before_the_run_record_still_loads(scanned_doc):
    """O JSON de uma versão sem `run` valida, com `run` vazio."""
    result = process(scanned_doc, policy="all_cheap", cheap=[FakeOCR()])
    old = result.model_dump(mode="json", exclude={"run"})
    assert type(result).model_validate(old).run is None


class TestFakeOCRContract(ReaderContract):
    """A suíte pública tem de passar no leitor de exemplo."""

    @pytest.fixture
    def reader(self):
        return FakeOCR()


# --- Custo: o que a biblioteca promete não gastar -----------------------------


def test_baseline_policies_never_pay_for_the_cheap_pass(scanned_doc):
    """`all_strong` descarta o texto barato, logo não pode mandar rodar OCR.

    Antes, a passagem barata era ansiosa: num auto de mil páginas isso era
    renderização mais Tesseract em TODAS elas, guardados num dict que a política
    jogava fora. Uma biblioteca sobre orçamento de leitura não pode gastar
    leitura que ninguém pediu.
    """
    ocr, vlm = FakeOCR(), FakeVLM()
    process(scanned_doc, policy="all_strong", cheap=[ocr], strong=vlm)
    assert ocr.calls == 0
    assert vlm.calls == 5


def test_a_policy_deciding_before_reads_only_pays_cheap_for_pages_it_keeps(scanned_doc):
    ocr, vlm = FakeOCR(), FakeVLM()
    process(scanned_doc, policy="all_strong", cheap=[ocr], strong=vlm)
    assert vlm.calls == 5
    assert ocr.calls == 0, "nenhuma página ficou no tier barato"


def test_escalated_page_is_rendered_once(monkeypatch, scanned_doc):
    """Uma página escalada era renderizada duas vezes: na passagem barata e na cara."""
    from docaudit import pdf as pdf_mod

    renders: list[int] = []
    real = pdf_mod.pixels_of

    def counting(pdf, index, **kw):
        renders.append(index)
        return real(pdf, index, **kw)

    monkeypatch.setattr(pdf_mod, "pixels_of", counting)
    process(scanned_doc, policy="all_strong", cheap=[FakeOCR()], strong=FakeVLM())
    assert sorted(renders) == [0, 1, 2, 3, 4]
    assert len(renders) == len(set(renders)), "nenhuma página renderizada duas vezes"


def test_an_escalated_page_keeps_its_render_across_the_stages(monkeypatch):
    """A leitura barata, a releitura e a leitura cara de uma página usam a mesma renderização."""
    from docaudit import pdf as pdf_mod

    renders: list[tuple[int, bool]] = []
    real = pdf_mod.pixels_of

    def counting(pdf, index, **kw):
        renders.append((index, kw.get("grayscale", True)))
        return real(pdf, index, **kw)

    monkeypatch.setattr(pdf_mod, "pixels_of", counting)
    cheap = _Says("cheap", {0: "CPF 529.982.247-26", 1: "limpo"})
    other = _Says("other", {0: "CPF 529.982.247-27"})
    doc = make_pdf(EMPTY_PAGE, EMPTY_PAGE)
    result = process(doc, policy="evidence", cheap=[cheap], confirm=other, strong=FakeVLM())
    assert result.decisions[0].tier is Tier.STRONG
    assert sorted(renders) == [(0, False), (0, True), (1, True)], (
        "a página escalada: cinza uma vez para os três leitores de cinza, RGB uma vez para o caro"
    )


def test_a_page_that_cannot_escalate_releases_its_render_during_the_cheap_stage():
    """Só a página com por onde escalar guarda a renderização; a memória não cresce com o auto."""
    import gc
    import weakref

    seen: dict[int, weakref.ref] = {}
    alive: dict[str, dict[int, bool]] = {}

    def snapshot(moment: str) -> None:
        gc.collect()
        alive[moment] = {i: ref() is not None for i, ref in seen.items()}

    class Recording(_Says):
        def read(self, view):
            if view.page.index == 2:
                snapshot("cheap")
            seen[view.page.index] = weakref.ref(view)
            return super().read(view)

    class Probe(FakeVLM):
        def read(self, view):
            snapshot("strong")
            return super().read(view)

    cheap = Recording("cheap", {0: "limpo", 1: "CPF 529.982.247-26", 2: "limpo"})
    doc = make_pdf(EMPTY_PAGE, EMPTY_PAGE, EMPTY_PAGE)
    result = process(doc, policy="evidence", cheap=[cheap], strong=Probe())
    assert [d.tier for d in result.decisions] == [Tier.CHEAP, Tier.STRONG, Tier.CHEAP]
    assert alive["cheap"] == {0: False, 1: True}, "a página limpa solta a renderização na hora"
    assert alive["strong"] == {0: False, 1: True, 2: False}


def test_a_hosted_strong_reader_reads_pages_in_parallel_with_the_same_result(scanned_doc):
    """Um leitor fora da máquina espera a rede: as páginas vão em paralelo, na mesma ordem."""
    alone = process(
        scanned_doc,
        policy="all_strong",
        cheap=[FakeOCR()],
        strong=ExternalVLM(),
        allow_external=True,
    )
    together = process(
        scanned_doc,
        policy="all_strong",
        cheap=[FakeOCR()],
        strong=ExternalVLM(),
        allow_external=True,
        workers=3,
    )
    assert [c.id for c in together.chunks] == [c.id for c in alone.chunks]
    assert [d.steps for d in together.decisions] == [d.steps for d in alone.decisions]
    assert together.spent.pages_strong == 5


def test_document_is_opened_once(monkeypatch, scanned_doc):
    """Cada função pública de pdf.py abria o documento de novo: ~3N aberturas."""
    from docaudit import pdf as pdf_mod

    opens = []
    real = pdf_mod._open

    def counting(document):
        opens.append(1)
        return real(document)

    monkeypatch.setattr(pdf_mod, "_open", counting)
    process(scanned_doc, policy="all_strong", cheap=[FakeOCR()], strong=FakeVLM())
    assert len(opens) == 1


def test_output_version_reaches_the_cache_key(tmp_path):
    """Dois leitores de mesmo nome e versões diferentes não partilham entrada."""
    from docaudit.cache import call_key

    cache = ModelCallCache(tmp_path / "c.sqlite")
    doc = make_pdf(EMPTY_PAGE)
    result = process(doc, policy="all_strong", cheap=[FakeOCR()], strong=FakeVLM(), cache=cache)
    page_dpi = load_pages(doc)[0].dimensions.dpi
    assert cache.get(call_key(result.doc_id, 0, page_dpi, "fake-vlm", "v1")) is not None
    assert cache.get(call_key(result.doc_id, 0, page_dpi, "fake-vlm", "v2")) is None
    cache.close()


def test_unknown_backend_name_fails_at_resolution_not_mid_read(monkeypatch, scanned_doc):
    """Um entry point mal registrado tem de falhar nomeando o contrato."""
    from docaudit import registry

    class NotABackend:
        pass

    class _EntryPoint:
        name = "quebrado"

        def load(self):
            return NotABackend

    monkeypatch.setattr(registry, "entry_points", lambda group: [_EntryPoint()])
    with pytest.raises(TypeError, match="não satisfaz o contrato Reader"):
        process(scanned_doc, policy="all_cheap", cheap=["quebrado"])


def test_a_reader_class_in_place_of_an_instance_fails_before_any_read(scanned_doc):
    """`strong=FakeVLM` sem os parênteses falharia só depois de pagar o tier barato."""
    # A classe no lugar da instância é o erro que o teste exercita, e o pyright o pega antes.
    strong = FakeVLM
    with pytest.raises(TypeError, match="passe uma instância, não a classe"):
        process(scanned_doc, policy="all_strong", cheap=["text_layer"], strong=strong)  # pyright: ignore[reportArgumentType]


# --- O que sai da máquina só sai com autorização -----------------------------


class ExternalVLM(FakeVLM):
    name = "vlm-externo"
    external = True


class ExternalReader(FakeOCR):
    name = "ocr-externo"
    external = True


def test_external_vlm_is_refused_by_default(scanned_doc):
    with pytest.raises(ExternalBackendError, match="vlm-externo"):
        process(scanned_doc, policy="all_strong", cheap=[FakeOCR()], strong=ExternalVLM())


def test_external_cheap_reader_is_refused_too(scanned_doc):
    """O portão vale para a cascata barata, não só para o tier caro."""
    with pytest.raises(ExternalBackendError, match="ocr-externo"):
        process(scanned_doc, policy="all_cheap", cheap=[ExternalReader()])


def test_external_is_allowed_with_explicit_consent(scanned_doc):
    vlm = ExternalVLM()
    result = process(
        scanned_doc, policy="all_strong", cheap=[FakeOCR()], strong=vlm, allow_external=True
    )
    assert vlm.calls == 5
    assert result.spent.pages_strong == 5.0


def test_refusal_happens_before_the_document_is_opened(monkeypatch, scanned_doc):
    """Um erro que só aparece na página 300 é pior que inútil."""
    from docaudit import pdf as pdf_mod

    def never_open(_document):
        raise AssertionError("o documento não deveria ter sido aberto")

    monkeypatch.setattr(pdf_mod, "_open", never_open)
    with pytest.raises(ExternalBackendError):
        process(scanned_doc, policy="all_cheap", cheap=[ExternalReader()])


def test_default_arguments_work():
    """`process(doc)` sem mais nada tem de funcionar.

    O padrão de `policy` era `signal_router`, que levanta `NotImplementedError`:
    a assinatura anunciava um padrão que não funcionava.
    """
    result = process(make_pdf(TEXT_CENTRAL))
    assert result.chunks
    assert {c.source for c in result.chunks} == {"text_layer"}
    assert result.spent.pages_strong == 0.0


# --- Paralelismo -------------------------------------------------------------


def test_parallel_gives_the_same_chunks_in_the_same_order():
    """`workers` é só velocidade: a saída tem de ser idêntica, ids e ordem."""
    doc = make_pdf(*[TEXT_CENTRAL] * 12)
    um = process(doc, cheap=["text_layer"], workers=1)
    oito = process(doc, cheap=["text_layer"], workers=8)
    assert [c.id for c in um.chunks] == [c.id for c in oito.chunks]
    assert [c.page for c in um.chunks] == [c.page for c in oito.chunks]


def test_every_page_is_read_exactly_once_in_parallel():
    doc = make_pdf(*[EMPTY_PAGE] * 9)
    ocr = FakeOCR()
    result = process(doc, cheap=[ocr], workers=4)
    assert ocr.calls == 9
    assert sorted(c.page for c in result.chunks) == list(range(9))


def test_workers_one_creates_no_pool():
    """O padrão não paga nada: sem pool e sem thread."""
    doc = make_pdf(*[EMPTY_PAGE] * 3)
    ocr = FakeOCR()
    assert process(doc, cheap=[ocr], workers=1).spent.pages_cheap == 3.0
    assert ocr.calls == 3


# --- Seleção de páginas e contabilidade de cache ------------------------------


def test_pages_restricts_what_is_read():
    """A etapa de zoom do padrão just-in-time: ler duas páginas, não o auto."""
    doc = make_pdf(*[EMPTY_PAGE] * 10)
    ocr = FakeOCR()
    result = process(doc, cheap=[ocr], pages={2, 7})
    assert ocr.calls == 2
    assert result.spent.pages_total == 2.0
    assert sorted(c.page for c in result.chunks) == [2, 7]


def test_unselected_pages_are_not_even_classified(monkeypatch):
    """Classificar mil páginas para ler duas é o custo que a triagem evita."""
    from docaudit import pdf as pdf_mod

    seen: list[int] = []
    real = pdf_mod._substrate_of

    def counting(page, **kw):
        seen.append(1)
        return real(page, **kw)

    monkeypatch.setattr(pdf_mod, "_substrate_of", counting)
    process(make_pdf(*[EMPTY_PAGE] * 10), cheap=[FakeOCR()], pages={3})
    assert len(seen) == 1


def test_spent_separates_cache_hits_from_real_calls(scanned_doc, tmp_path):
    """Uma execução servida pelo cache não pode reportar o mesmo gasto de uma real."""
    cache = ModelCallCache(tmp_path / "c.sqlite")
    kwargs = {"policy": "all_strong", "cheap": [FakeOCR()], "cache": cache}

    vlm = FakeVLM()
    first_page = process(scanned_doc, strong=vlm, **kwargs)
    assert vlm.calls == 5
    assert first_page.spent.pages_strong_cached == 0.0

    segunda = process(scanned_doc, strong=FakeVLM(), **kwargs)
    assert segunda.spent.pages_strong == 5.0
    assert segunda.spent.pages_strong_cached == 5.0, "tudo do cache, nenhum modelo tocado"
    cache.close()


def test_parallel_reading_is_stable_over_many_pages():
    """Exercita o laço paralelo com páginas suficientes para expor corrida.

    O pdfium não é seguro para uso concorrente, e `PdfPage` tem finalizador: um
    objeto coletado noutra thread fecharia a página fora do lock. Com poucas
    páginas o laço não interleava o bastante para o problema aparecer.
    """
    doc = make_pdf(*[TEXT_CENTRAL] * 60)
    serial = process(doc, cheap=["text_layer"], workers=1)
    for _ in range(3):
        parallel = process(doc, cheap=["text_layer"], workers=8)
        assert [c.id for c in parallel.chunks] == [c.id for c in serial.chunks]
        assert parallel.spent.pages_total == 60.0


# --- Política que decide sobre a leitura barata --------------------------------


def test_the_hidden_layer_of_a_searchable_scan_is_not_a_read_by_default():
    """A camada que um OCR desconhecido deixou não é leitura: o leitor de pixels lê a página."""
    ocr = FakeOCR()
    result = process(make_scanned_pdf(["EDITAL DE CONVOCACAO"]), cheap=["text_layer", ocr])
    assert ocr.calls == 1
    assert [c.source for c in result.chunks] == ["fake-ocr"]


def test_the_hidden_layer_is_read_as_is_when_trusted():
    ocr = FakeOCR()
    result = process(
        make_scanned_pdf(["EDITAL DE CONVOCACAO"]), cheap=["text_layer", ocr], trust_layer="always"
    )
    assert ocr.calls == 0
    assert [c.text for c in result.chunks] == ["EDITAL DE CONVOCACAO"]


def test_the_hidden_layer_is_the_first_family_of_the_reread():
    """A camada que confere no mesmo lugar conserta a linha; a que repete o inválido o confirma."""
    vlm = FakeVLM()
    fixed = process(
        make_scanned_pdf(["CPF 529.982.247-25"]),
        policy="evidence",
        cheap=["text_layer", _Says("cheap", {0: "CPF 529.982.247-26"})],
        strong=vlm,
    )
    (decision,) = fixed.decisions
    assert decision.tier is Tier.CHEAP
    assert decision.reason == "corrigido por text_layer"
    assert [c.text for c in fixed.chunks] == ["CPF 529.982.247-25"]
    assert vlm.calls == 0
    assert fixed.spent.pages_confirmed_fixed == 1

    same = process(
        make_scanned_pdf(["CPF 529.982.247-26"]),
        policy="evidence",
        cheap=["text_layer", _Says("cheap", {0: "CPF 529.982.247-26"})],
        strong=vlm,
    )
    assert same.decisions[0].reason == "erro do documento: text_layer leu o mesmo"
    assert vlm.calls == 0


def test_a_layer_tesseract_wrote_does_not_confirm_what_tesseract_read():
    """A camada com `GlyphLessFont` é do Tesseract: não é outra família para o Tesseract."""
    doc = make_scanned_pdf(["CPF 529.982.247-26"], font="GlyphLessFont")
    assert load_pages(doc)[0].hidden_fonts == ("GlyphLessFont",)
    same = process(
        doc, policy="evidence", cheap=["text_layer", _Says("tesseract", {0: "CPF 529.982.247-26"})]
    )
    (decision,) = same.decisions
    assert not decision.reason.startswith("erro do documento")
    assert any("mesmo motor" in s for s in decision.steps)
    (cpf,) = same.entities
    assert cpf.printed is None

    other = process(
        doc, policy="evidence", cheap=["text_layer", _Says("cheap", {0: "CPF 529.982.247-26"})]
    )
    assert other.decisions[0].reason == "erro do documento: text_layer leu o mesmo"
    assert other.entities[0].printed == "text_layer"


def test_a_layer_tesseract_wrote_does_not_fix_what_tesseract_read_but_its_id_still_enters():
    """Sem releitura pela camada, a página escala; o id que confere na camada entra depois."""
    doc = make_scanned_pdf(["CPF 529.982.247-25"], font="GlyphLessFont")
    result = process(
        doc, policy="evidence", cheap=["text_layer", _Says("tesseract", {0: "CPF 529.982.247-26"})]
    )
    (decision,) = result.decisions
    assert decision.tier is Tier.STRONG, "a camada do mesmo motor não conserta"
    assert ("CPF 529.982.247-25", "text_layer") in [(c.text, c.source) for c in result.chunks]


def test_evidence_reads_every_page_cheap_then_escalates_only_the_proven_failures():
    failing_cpf = "BT /F1 24 Tf 100 400 Td (CPF 529.982.247-26) Tj ET"
    doc = make_pdf(TEXT_CENTRAL, failing_cpf, EMPTY_PAGE)
    ocr, vlm = FakeOCR(), FakeVLM()
    result = process(doc, policy="evidence", cheap=["text_layer", ocr], strong=vlm)

    assert ocr.calls == 1, "só a página sem texto vai ao OCR barato"
    assert vlm.calls == 1, "o CPF quebrado está em texto composto: erro do documento"
    assert [d.tier for d in result.decisions] == [Tier.CHEAP, Tier.CHEAP, Tier.STRONG]
    assert {c.page: c.source for c in result.chunks} == {
        0: "text_layer",
        1: "text_layer",
        2: "fake-vlm",
    }
    assert result.spent.pages_cheap == 3.0, "toda página paga a leitura barata"
    assert result.spent.pages_strong == 1.0


def test_evidence_escalates_a_misread_id_on_a_searchable_scan():
    """A camada de OCR de origem leu um CPF errado: a página merece releitura."""
    vlm = FakeVLM(text="CPF 529.982.247-25")
    result = process(
        make_scanned_pdf(["CPF 529.982.247-26"]),
        policy="evidence",
        cheap=["text_layer"],
        strong=vlm,
        trust_layer="always",
    )
    assert vlm.calls == 1
    assert "falha a verificação" in result.decisions[0].reason
    assert [c.source for c in result.chunks] == ["fake-vlm"]


def test_a_region_reader_replaces_only_what_it_read():
    """O leitor caro por região descarta a margem; a linha barata de fora dela fica."""
    body = BBox(x0=0.0, y0=0.5, x1=1.0, y1=1.0)
    vlm = FakeVLM(box=body)
    result = process(
        make_scanned_pdf(["CPF 529.982.247-26"]),
        policy="evidence",
        cheap=["text_layer"],
        strong=vlm,
        trust_layer="always",
    )
    assert vlm.calls == 1
    assert [c.source for c in result.chunks] == ["fake-vlm", "text_layer"]
    assert result.chunks[1].reading_order is None


def test_a_marked_hyphen_and_a_symbol_bullet_do_not_route_the_page():
    """Nenhum dos dois é decodificação quebrada: a página fica no tier barato."""
    doc = make_pdf(
        "BT /F1 12 Tf 100 400 Td (x Responsavel pela im-) Tj 0 -14 Td (plantacao) Tj ET",
        to_unicode={"x": "\uf0b7"},
    )
    result = process(doc, policy="evidence", cheap=["text_layer"])
    assert result.decisions[0].tier is Tier.CHEAP
    (chunk,) = result.chunks
    assert chunk.text == "\u2022 Responsavel pela im-plantacao"
    assert chunk.line_break_hyphens == (21,)


def test_garbled_lines_outside_the_strong_boxes_are_dropped():
    """Escalada por texto mal decodificado, a página não devolve o lixo fora do que o caro leu."""
    doc = make_pdf(
        "BT /F1 12 Tf 100 700 Td (xxxx xxx) Tj ET "
        "BT /F1 12 Tf 100 150 Td (linha limpa no pe da folha) Tj ET "
        "BT /F1 12 Tf 100 100 Td (xxx xxxx) Tj ET",
        to_unicode={"x": "\ufffd"},
    )
    top = BBox(x0=0.0, y0=0.0, x1=1.0, y1=0.5)
    result = process(doc, policy="evidence", cheap=["text_layer"], strong=FakeVLM(box=top))
    assert result.decisions[0].tier is Tier.STRONG
    assert [(c.source, c.text) for c in result.chunks] == [
        ("fake-vlm", "vlm pagina 0"),
        ("text_layer", "linha limpa no pe da folha"),
    ]
    assert any("mal decodificada" in step for step in result.decisions[0].steps)


def test_a_path_given_as_str_is_read_like_a_path(tmp_path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(make_pdf(TEXT_CENTRAL))
    assert load_pages(str(path)) == load_pages(path)


def test_evidence_without_a_vlm_keeps_the_cheap_read():
    doc = make_scanned_pdf(["CPF 529.982.247-26"])
    result = process(doc, policy="evidence", cheap=["text_layer"], trust_layer="always")
    assert [c.source for c in result.chunks] == ["text_layer"]
    assert result.decisions[0].tier is Tier.STRONG, (
        "a decisão fica registrada mesmo sem quem a execute"
    )


# --- A forma da saída ---------------------------------------------------------


def test_result_carries_the_pages_and_the_time_per_tier():
    """Quem recebe o Result não precisa reclassificar o PDF nem cronometrar nada."""
    doc = make_pdf(TEXT_CENTRAL, EMPTY_PAGE)
    result = process(doc, policy="all_strong", cheap=[FakeOCR()], strong=FakeVLM(), pages={1})
    assert [p.index for p in result.pages] == [1]
    assert result.pages[0].substrate_evidence["chars"] == 0.0
    assert result.spent.seconds_strong > 0.0
    assert result.spent.seconds_cheap < result.spent.seconds_strong, "nada foi lido no barato"
    assert result.spent.seconds >= result.spent.seconds_strong


def test_chunk_ids_do_not_depend_on_rendering_or_cache(tmp_path):
    """O mesmo documento, lido com e sem cache, dá os mesmos ids: nenhum pixel entra neles."""
    doc = make_pdf(TEXT_CENTRAL, EMPTY_PAGE)
    cache = ModelCallCache(tmp_path / "c.sqlite")
    first = process(doc, cheap=["text_layer", FakeOCR()], cache=cache)
    second = process(doc, cheap=["text_layer", FakeOCR()], cache=cache)
    assert [c.id for c in first.chunks] == [c.id for c in second.chunks]
    chunk = next(c for c in first.chunks if c.page == 1)
    page = first.pages[1]
    assert chunk.id == Chunk.make_id(Chunk.key_of(page), chunk.bbox, "fake-ocr", chunk.text, page=1)
    cache.close()


def test_a_page_the_expensive_reader_fails_keeps_its_cheap_read_and_is_counted():
    """Um servidor que rejeita uma página em cinquenta não pode derrubar o auto inteiro."""

    class FlakyVLM(FakeVLM):
        def read(self, view):
            if view.page.index == 1:
                raise RuntimeError("llama-server respondeu 500: Failed to parse input")
            return super().read(view)

    doc = make_pdf(TEXT_CENTRAL, EMPTY_PAGE, TEXT_CENTRAL)
    with pytest.warns(RuntimeWarning, match="página 1"):
        result = process(doc, policy="all_strong", cheap=[FakeOCR()], strong=FlakyVLM())
    assert result.spent.pages_strong == 2.0
    assert result.spent.pages_strong_failed == 1.0
    assert {c.page for c in result.chunks} == {0, 2}, "sem leitura barata, a página fica vazia"

    with pytest.warns(RuntimeWarning):
        kept = process(doc, policy="evidence", cheap=[FakeOCR()], strong=FlakyVLM())
    assert {c.source for c in kept.chunks if c.page == 1} == {"fake-ocr"}, "a barata fica"

    class Absent(FakeVLM):
        def read(self, view):
            raise ConnectionError("sem llama-server")

    with pytest.raises(ConnectionError):
        process(doc, policy="all_strong", cheap=[FakeOCR()], strong=Absent())


def test_exports_keep_page_order_and_provenance():
    doc = make_pdf(TEXT_CENTRAL, EMPTY_PAGE)
    result = process(doc, cheap=["text_layer", FakeOCR()])
    md = result.to_markdown()
    assert md.index("página 0 · text_layer") < md.index("página 1 · fake-ocr")
    assert "EDITAL DE CITACAO" in md

    assert list(result.by_page()) == [0, 1]
    assert Chunk.model_validate_json(result.chunks[0].model_dump_json()) == result.chunks[0]


# ── Rasters que a camada de texto não leu ─────────────────────────────────────


def test_a_scan_with_a_stamped_footer_has_its_body_read_as_a_region(tmp_path):
    """O rodapé vem da camada de texto; o corpo, do leitor seguinte, antes dele e sem repeti-lo."""
    doc = make_scanned_pdf(["Num. 41560374 - Pag. 2"], render_mode=0, text_y=30)
    ocr = FakeOCR()
    cache = ModelCallCache(tmp_path / "c.sqlite")
    result = process(doc, cheap=["text_layer", ocr], cache=cache)
    assert [c.source for c in result.chunks] == ["fake-ocr", "text_layer"]
    body, footer = result.chunks
    assert body.text == "ocr pagina 0"
    assert (body.region, footer.region) == (0, None), "o corpo diz de qual raster veio"
    assert (body.reading_order, footer.reading_order) == (0, 1), "o corpo antes do rodapé"
    assert result.spent.regions_cheap == 1.0
    assert ocr.calls == 1

    again = process(doc, cheap=["text_layer", ocr], cache=cache)
    assert [c.text for c in again.chunks] == [c.text for c in result.chunks]
    assert ocr.calls == 1, "a região vem do cache"
    cache.close()


def test_a_region_line_centred_on_a_text_layer_line_is_dropped():
    """O OCR do rodapé carimbado seria o rodapé duas vezes.

    O dublê lê uma linha de 0,1 a 0,9 da largura, centrada em 0,15 da altura;
    a linha da camada passa por esse centro.
    """
    stamp = "Num. 41560374 - Pag. 2 - assinado digitalmente por fulano de tal da silva"
    doc = make_scanned_pdf([stamp], render_mode=0, text_y=712)
    result = process(doc, cheap=["text_layer", FakeOCR()])
    assert [c.source for c in result.chunks] == ["text_layer"]


def test_a_diagonal_watermark_does_not_hide_the_scan_under_it():
    """A caixa da marca d'água em diagonal cobre quase a folha, mas a marca não leu o corpo."""
    doc = make_scanned_pdf(slanted="COPIA - DOCUMENTO DIGITAL")
    result = process(doc, cheap=["text_layer", FakeOCR()])
    (watermark,) = (c for c in result.chunks if c.source == "text_layer")
    box = watermark.bbox
    assert (box.x0 < 0.5 < box.x1, box.y0 < 0.15 < box.y1) == (True, True), "cobre a linha do OCR"
    assert "ocr pagina 0" in [c.text for c in result.chunks]


def test_a_typeset_page_without_rasters_never_reaches_the_ocr():
    ocr = FakeOCR()
    result = process(make_pdf(TEXT_CENTRAL), cheap=["text_layer", ocr])
    assert ocr.calls == 0
    assert result.spent.regions_cheap == 0.0


def test_a_layer_in_a_font_without_unicode_map_goes_to_the_pixel_reader():
    ocr = FakeOCR()
    result = process(make_pdf(TEXT_CENTRAL, to_unicode={"E": "\x05"}), cheap=["text_layer", ocr])
    assert ocr.calls == 1
    assert {c.source for c in result.chunks} == {ocr.name}


def test_a_line_inside_two_overlapping_unread_regions_comes_back_once():
    """A fonte sem mapa por cima da digitalização: duas regiões sem leitura, uma linha."""
    doc = make_scanned_pdf(["fls. 1"], render_mode=0, text_y=780)
    with opened(doc) as pdf:
        (page,) = pages_of(pdf, "t")
        inner = BBox(x0=0.05, y0=0.05, x1=0.95, y1=0.3)
        view = PageView(pdf, page.model_copy(update={"unread": (*page.unread, inner)}))
        chunks = _read_cascade(view, [TextLayerReader(), FakeOCR()], None).chunks
    assert [c.text for c in chunks].count("ocr pagina 0") == 1


class _ReadsFigure:
    """Leitor de pixels que devolve uma linha centrada no raster de uma página composta."""

    name = "fake-figure"
    external = False
    output_version = "v1"

    def read(self, view):
        view.image()
        page = view.page
        bbox = BBox(x0=0.2, y0=0.44, x1=0.8, y1=0.47)
        return [Chunk.make(page, bbox, self.name, "legenda na figura", reading_order=0)]


class _SeesTheCrop:
    """Um leitor de pixels que anota o tamanho do que viu e lê uma linha no meio dele."""

    name = "sees-the-crop"
    output_version = "1"
    external = False

    def __init__(self) -> None:
        self.seen: list[tuple[int, int]] = []

    def read(self, view):
        view.image()
        dims = view.page.dimensions
        self.seen.append((dims.width_px, dims.height_px))
        # Duas linhas, a um quarto e a três quartos da largura do que viu: num
        # recorte de um raster só, as duas caem nele; num recorte de dois
        # rasters vizinhos, uma em cada.
        return [
            Chunk.make(
                view.page,
                BBox(x0=x, y0=0.45, x1=x + 0.1, y1=0.55),
                self.name,
                text,
                reading_order=n,
            )
            for n, (x, text) in enumerate([(0.2, "um"), (0.7, "dois")])
        ]


def test_the_raster_goes_to_the_pixel_reader_as_a_crop_with_its_margin():
    """O leitor vê o recorte do raster com a folga, não a folha; a linha volta ao raster."""
    reader = _SeesTheCrop()
    doc = make_scanned_pdf(["acima"], render_mode=0, raster_box=(0.3, 0.3, 0.7, 0.5), text_y=780)
    result = process(doc, policy="all_cheap", cheap=["text_layer", reader])
    page = result.pages[0]
    (raster,) = page.unread
    x0, y0, x1, y1 = raster.padded(RASTER_MARGIN).to_pixels(
        page.dimensions.width_px, page.dimensions.height_px
    )
    assert reader.seen == [(x1 - x0, y1 - y0)], "o recorte com a folga, não a folha"
    assert [c.text for c in result.chunks if c.region == 0] == ["um", "dois"]


def test_a_reader_sees_which_rasters_its_crop_reads_and_can_decline_a_small_one():
    """A região diz que imagem da página ela lê: o leitor recusa o logotipo e a página fica
    com a camada, numa chamada só."""
    from docaudit.pdf import RegionView

    class _SkipsSmall(_SeesTheCrop):
        def __init__(self) -> None:
            super().__init__()
            self.rasters: list[tuple[BBox, ...]] = []

        def read(self, view):
            if isinstance(view, RegionView):
                self.rasters.append(view.rasters)
                if max(r.area for r in view.rasters) < 0.15:
                    return []
            return super().read(view)

    reader = _SkipsSmall()
    doc = make_scanned_pdf(["acima"], render_mode=0, raster_box=(0.1, 0.4, 0.3, 0.5), text_y=780)
    result = process(doc, policy="all_cheap", cheap=["text_layer", reader])
    ((raster,),) = reader.rasters
    assert raster == result.pages[0].unread[0], "a imagem da página, na caixa da página"
    assert [c.source for c in result.chunks] == ["text_layer"]
    assert reader.seen == [], "o recorte recusado não é lido"


def test_two_rasters_close_together_are_one_crop_and_each_keeps_its_lines():
    """Dois logotipos vizinhos: um recorte só para o leitor, e cada linha volta ao seu raster."""
    reader = _SeesTheCrop()
    doc = make_scanned_pdf(
        ["acima"],
        render_mode=0,
        raster_box=(0.55, 0.3, 0.75, 0.5),
        extra_raster_boxes=[(0.25, 0.3, 0.45, 0.5)],
        text_y=780,
    )
    result = process(doc, policy="all_cheap", cheap=["text_layer", reader])
    assert len(result.pages[0].unread) == 2
    assert len(reader.seen) == 1, "as folgas se tocam: um recorte"
    assert sorted(c.region for c in result.chunks if c.region is not None) == [0, 1]


def _stamped(*lines: str) -> str:
    """Um content stream com linhas de texto à vista, uma por argumento, como a tarja do e-SAJ."""
    ops = " ".join(
        f"BT /F1 9 Tf 40 {800 - 14 * n} Td ({line}) Tj ET" for n, line in enumerate(lines)
    )
    return ops


def _strip(process_number: str, code: str, *, signer: str = "FULANO DE TAL") -> tuple[str, str]:
    """As duas linhas da tarja de uma peça protocolada, sem acento como a fonte do teste."""
    return (
        f"Este documento e copia do original, assinado digitalmente por {signer}, "
        "protocolado em 23/05/2020 as 15:19 , sob o numero WJMJ20406814970 .",
        "Para conferir o original, acesse o site https://esaj.tjsp.jus.br/pastadigital/pg/"
        f"abrirConferenciaDocumento.do, informe o processo {process_number} e codigo {code}.",
    )


_OWN = "9000705-10.2024.8.26.0354"


def test_the_page_carries_its_own_stamp():
    """A tarja dá a peça, quem a assinou e quando; a tarja copiada de outro processo não conta."""
    released = (
        "Este documento e copia do original, assinado digitalmente por JUIZ DE DIREITO, "
        "liberado nos autos em 06/08/2024 as 09:40 .",
        _strip(_OWN, "Zz9Yy8Xx")[1],
    )
    two_signers = _strip(_OWN, "Qq1Ww2Ee", signer="BELTRANO e Tribunal de Justica")
    doc = make_pdf(
        _stamped("Peticao inicial", *_strip(_OWN, "AbCd1234")),
        _stamped("Pagina dois da peticao", *_strip(_OWN, "AbCd1234")),
        _stamped(
            "Documento copiado de outro processo",
            *_strip("9166825-29.2024.8.26.0100", "ZzZz9999"),
            *_strip(_OWN, "EfGh5678"),
        ),
        _stamped("Decisao", *released),
        _stamped("Folha sem tarja"),
        _stamped("Dois signatarios", two_signers[0].replace(" .", ""), two_signers[1]),
    )
    result = process(doc, policy="all_cheap", cheap=["text_layer"])
    assert [p.stamp.code if p.stamp else None for p in result.pages] == [
        "AbCd1234",
        "AbCd1234",
        "EfGh5678",
        "Zz9Yy8Xx",
        None,
        "Qq1Ww2Ee",
    ]
    grounding = {"bbox", "chunk_ids"}
    first, released = result.pages[0].stamp, result.pages[3].stamp
    assert first is not None
    assert released is not None
    assert first.model_dump(exclude=grounding) == {
        "format": "e-saj",
        "process": _OWN,
        "code": "AbCd1234",
        "signer": "FULANO DE TAL",
        "at": datetime(2020, 5, 23, 15, 19),
        "protocol": "WJMJ20406814970",
    }
    assert (released.signer, released.protocol) == ("JUIZ DE DIREITO", None)
    lines = {c.id: c.text for c in result.chunks}
    assert [lines[i][:13] for i in first.chunk_ids] == ["Este document", "Para conferir"], (
        "a tarja aponta as duas linhas de onde veio"
    )
    two = result.pages[5].stamp
    assert two is not None
    assert two.signer == "BELTRANO e Tribunal de Justica", "sem o ponto antes de Para conferir"
    text = result.to_markdown(annotated=True)
    assert "<!-- página 0 · text_layer · documento AbCd1234 (p0:1, p0:2) -->" in text
    assert "<!-- página 4 · text_layer -->" in text
    assert "· documento" not in result.to_markdown()


def test_each_page_of_a_bundle_keeps_the_stamp_of_its_own_process():
    """Um PDF que junta peças de dois processos: a tarja é da página, não da maioria."""
    other = "9166825-29.2024.8.26.0100"
    doc = make_pdf(
        _stamped("Peca um", *_strip(_OWN, "AbCd1234")),
        _stamped("Peca dois", *_strip(other, "ZzZz9999")),
        _stamped("Peca tres", *_strip(other, "ZzZz9999")),
    )
    result = process(doc, policy="all_cheap", cheap=["text_layer"])
    assert [p.stamp.process if p.stamp else None for p in result.pages] == [_OWN, other, other]


def test_stamps_are_looked_for_only_in_the_formats_asked():
    """`[]` não procura tarja; um formato próprio acha a tarja de outro sistema."""
    pje = StampFormat("pje", re.compile(r"Num\. (?P<code>\d+) - Pag\. \d+"))
    doc = make_pdf(
        _stamped("Peticao", *_strip(_OWN, "AbCd1234")),
        _stamped("Decisao", "Num. 123456789 - Pag. 1"),
    )
    assert all(p.stamp is None for p in process(doc, cheap=["text_layer"], stamps=[]).pages)
    result = process(doc, policy="all_cheap", cheap=["text_layer"], stamps=[ESAJ_STAMP, pje])
    assert [(p.stamp.format, p.stamp.code) for p in result.pages if p.stamp] == [
        ("e-saj", "AbCd1234"),
        ("pje", "123456789"),
    ]
    assert result.pages[1].stamp is not None
    assert result.pages[1].stamp.process is None
    assert result.run is not None
    assert result.run.stamps == ("e-saj", "pje")
    with pytest.raises(ValueError, match="code"):
        StampFormat("sem-id", re.compile(r"Num\. \d+"))


def test_stamp_formats_come_by_name_and_read_their_own_time():
    """`stamps=` aceita o nome de um formato; o formato lê a hora no layout dele."""
    go = (
        "Documento Assinado e Publicado Digitalmente em 19/08/2019 15:30:31",
        "Assinado por FULANO DE TAL",
        "Localizar pelo codigo: 123456789012345678901234567, no endereco: https://x",
    )
    doc = make_pdf(_stamped("Decisao", *go))
    (page,) = process(doc, policy="all_cheap", cheap=["text_layer"], stamps=["projudi-go"]).pages
    assert page.stamp is not None
    assert (page.stamp.format, page.stamp.code) == ("projudi-go", "123456789012345678901234567")
    assert page.stamp.at == datetime(2019, 8, 19, 15, 30, 31)
    with pytest.raises(ValueError, match="aceitos"):
        process(doc, cheap=["text_layer"], stamps=["sem-nome"])


def test_a_stamp_whose_process_fails_the_check_digit_is_not_a_stamp():
    """A tarja cujo CNJ não confere não é tarja; o formato sem CNJ desliga a conferência."""
    wrong = "9000705-11.2024.8.26.0354"
    doc = make_pdf(_stamped("Peticao", *_strip(wrong, "AbCd1234")))
    assert process(doc, policy="all_cheap", cheap=["text_layer"]).pages[0].stamp is None
    loose = StampFormat(
        "sem-cnj",
        re.compile(r"processo (?P<process>\S+) e codigo (?P<code>\w+)"),
        process_check=None,
    )
    (page,) = process(doc, policy="all_cheap", cheap=["text_layer"], stamps=[loose]).pages
    assert page.stamp is not None
    assert page.stamp.process == wrong


@pytest.mark.parametrize(
    ("name", "lines", "code", "process_number"),
    [
        (
            "pje",
            (
                "Assinado eletronicamente por: FULANO DE TAL - 01/07/2022 11:47:34 "
                "Num. 12345 - Pag. 1",
                "https://pje.tjmg.jus.br:443/pje/Processo/ConsultaDocumento/listView.seam?x=1",
                "Numero do documento: 11111111111111111111111111111",
            ),
            "11111111111111111111111111111",
            None,
        ),
        (
            "projudi-pr",
            (
                "Documento assinado digitalmente, conforme MP n 2.200-2/2001, Lei n 11.419/2006",
                "Validacao deste em https://projudi.tjpr.jus.br - "
                "Identificador: PJAAA BBBBB CCCCC DDDDD",
                "PROJUDI - Processo: 1234567-09.2018.8.16.0033 - Ref. mov. 10.1 - "
                "Assinado digitalmente por FULANO DE TAL",
            ),
            "PJAAA BBBBB CCCCC DDDDD",
            "1234567-09.2018.8.16.0033",
        ),
        (
            "eproc",
            ("Processo 7654321-55.2024.8.21.0019/RS, Evento 10, ANEXO2, Pagina 3",),
            "Evento 10, ANEXO2",
            "7654321-55.2024.8.21.0019",
        ),
    ],
)
def test_each_preset_reads_the_stamp_of_its_own_system(name, lines, code, process_number):
    """A forma das linhas é a vista em páginas reais do sistema, com nomes e números trocados."""
    doc = make_pdf(_stamped("Peca", *lines))
    (page,) = process(doc, policy="all_cheap", cheap=["text_layer"], stamps=[name]).pages
    assert page.stamp is not None
    assert (page.stamp.format, page.stamp.code, page.stamp.process) == (name, code, process_number)
    others = [n for n in ("e-saj", "pje", "projudi-pr", "projudi-go", "eproc") if n != name]
    (alone,) = process(doc, policy="all_cheap", cheap=["text_layer"], stamps=others).pages
    assert alone.stamp is None, "nenhum outro formato casa a tarja deste sistema"


def test_the_stamp_drawn_last_wins_even_when_its_lines_are_drawn_out_of_order():
    """O tribunal desenha a segunda linha da tarja antes da primeira: a tarja casa na ordem
    do texto, e a ordem de desenho só escolhe entre as tarjas."""
    (page,) = load_pages(make_pdf(_stamped("Copia")))
    box = BBox(x0=0.95, y0=0.1, x1=0.99, y1=0.9)
    origin = _strip("9166825-29.2024.8.26.0100", "ZzZz9999", signer="BELTRANO")
    own = _strip(_OWN, "EfGh5678")
    lines = [
        Chunk.make(page, box, "text_layer", text, reading_order=i)
        for i, text in enumerate([*origin, *own])
    ]
    drawn = {lines[1].id: 0, lines[0].id: 1, lines[3].id: 2, lines[2].id: 3}
    (stamp,) = stamps_of({0: lines}, drawn=lambda _: drawn).values()
    assert stamp.code == "EfGh5678"
    reversed_drawing = {lines[3].id: 0, lines[2].id: 1, lines[1].id: 2, lines[0].id: 3}
    (stamp,) = stamps_of({0: lines}, drawn=lambda _: reversed_drawing).values()
    assert stamp.code == "ZzZz9999"


def test_a_stamp_with_a_date_that_does_not_exist_is_not_a_stamp():
    line = _strip(_OWN, "AbCd1234")[0].replace("23/05/2020", "31/02/2020")
    doc = make_pdf(_stamped("Peticao", line, _strip(_OWN, "AbCd1234")[1]))
    assert process(doc, policy="all_cheap", cheap=["text_layer"]).pages[0].stamp is None


def _folha_page(*stamps: int, body: str = "Corpo proprio") -> str:
    """Uma página com o carimbo de folha no alto, à direita, e um corpo que cita outra folha.

    Mais de um carimbo é a cópia de outro processo: o da origem vem com a página
    copiada, antes do corpo, e o do tribunal é desenhado por último, no mesmo lugar.
    """
    *origin, own = stamps
    return "\n".join(
        [
            *(f"BT /F1 8 Tf 520 820 Td (fls. {n}) Tj ET" for n in origin),
            f"BT /F1 10 Tf 70 600 Td ({body}, conforme fls. 12) Tj ET",
            f"BT /F1 8 Tf 520 820 Td (fls. {own}) Tj ET",
        ]
    )


def test_the_folha_is_the_stamp_on_a_fixed_line_and_not_the_one_cited_in_the_body():
    """O carimbo repetido no mesmo lugar é a folha; `fls. 12` no corpo é citação.

    A terceira página é a cópia de outro processo: a folha 24 da origem vem antes
    da 103 que o tribunal desenhou por cima."""
    doc = make_pdf(
        _folha_page(101, body="Alfa"),
        _folha_page(102, body="Beta"),
        _folha_page(24, 103, body="Gama"),
        _folha_page(104, body="Delta"),
    )
    result = process(doc, policy="all_cheap", cheap=["text_layer"])
    assert all(p.folha is not None and p.folha.in_sequence for p in result.pages)
    assert [p.folha.value if p.folha else None for p in result.pages] == [101, 102, 103, 104], (
        "a cópia traz o carimbo da origem no mesmo lugar: vale o último desenhado"
    )
    cited = [e for e in result.entities if e.kind == "folha" and e.value == "fls. 12"]
    assert len(cited) == 4, "a citação segue entidade"
    lines = {c.id: c for c in result.chunks}
    assert not any(lines[i].furniture for e in cited for i in e.chunk_ids)
    folha = result.pages[2].folha
    assert folha is not None
    assert lines[folha.chunk_ids[0]].text == "fls. 103", "a folha aponta a linha do carimbo"
    assert "· fls. 102 (p1:1) -->" in result.to_markdown(annotated=True)


def test_a_folha_read_in_the_pixels_counts_when_the_layer_has_none():
    """A tarja fixa vem da camada e não traz folha; o carimbo veio do leitor de pixels."""
    (page,) = load_pages(make_pdf(_stamped("Peticao")))
    box = BBox(x0=0.8, y0=0.0, x1=0.95, y1=0.03)
    strip = Chunk.make(
        page, box, "text_layer", "Este documento e copia do original", reading_order=0
    )
    stamp = Chunk.make(page, box, "ppocr-v5-latin", "fls. 7576", reading_order=0)
    lines = [c.model_copy(update={"furniture": True}) for c in (strip, stamp)]
    folha = folhas_of({0: lines})[0]
    assert (folha.value, folha.chunk_ids) == (7576, (stamp.id,))


def test_the_folha_form_is_chosen_by_the_caller():
    """`folhas=` troca a forma da folha: a página do Projudi, ou nenhuma."""
    pages = [
        "\n".join(
            [
                f"BT /F1 10 Tf 70 600 Td (Corpo {body}) Tj ET",
                f"BT /F1 8 Tf 500 20 Td (Pagina {n}) Tj ET",
            ]
        )
        # Corpos com letras diferentes: páginas que só diferem nos números são cópia.
        for n, body in (("9.118", "Alfa"), ("9.119", "Beta"))
    ]
    doc = make_pdf(*pages)
    page_form = Check("pagina", re.compile(r"Pagina (?P<number>[0-9.]+)"), lambda _: True)
    result = process(doc, policy="all_cheap", cheap=["text_layer"], folhas=[page_form])
    assert [p.folha.value if p.folha else None for p in result.pages] == [9118, 9119]
    assert result.run is not None
    assert result.run.folhas == ("pagina",)
    plain = process(doc, policy="all_cheap", cheap=["text_layer"], folhas=[])
    assert all(p.folha is None for p in plain.pages)
    with pytest.raises(ValueError, match="number"):
        process(doc, cheap=["text_layer"], folhas=[Check("x", re.compile("Pagina"), bool)])


def test_the_last_stamp_is_the_last_drawn_and_not_the_last_in_text_order():
    """Duas folhas fixas na camada: vale a desenhada por último, mesmo fora da ordem do texto."""
    (page,) = load_pages(make_pdf(_stamped("Copia")))
    box = BBox(x0=0.8, y0=0.0, x1=0.95, y1=0.03)
    own = Chunk.make(page, box, "text_layer", "fls. 103", reading_order=0)
    origin = Chunk.make(page, box, "text_layer", "fls. 24", reading_order=1)
    lines = [c.model_copy(update={"furniture": True}) for c in (own, origin)]
    assert folhas_of({0: lines})[0].value == 24, "sem a ordem de desenho, vale a do texto"
    drawn = folhas_of({0: lines}, drawn=lambda _: {origin.id: 0, own.id: 5})[0]
    assert drawn.value == 103


def test_text_lines_carry_their_place_in_the_drawing_order():
    stream = "\n".join(
        [
            "BT /F1 8 Tf 520 820 Td (fls. 24) Tj ET",
            "BT /F1 10 Tf 70 600 Td (Corpo) Tj ET",
            "BT /F1 8 Tf 520 700 Td (fls. 103) Tj ET",
        ]
    )
    with opened(make_pdf(stream)) as pdf:
        assert [(d.line.text, d.drawn, d.visible) for d in drawn_lines_of(pdf, 0)] == [
            ("fls. 24", 0, True),
            ("Corpo", 1, True),
            ("fls. 103", 2, True),
        ]


def test_a_folha_out_of_the_sequence_of_the_run_is_flagged():
    """Um documento juntado com numeração própria no meio do auto sai fora da sequência."""
    doc = make_pdf(
        _folha_page(101, body="Alfa"),
        _folha_page(102, body="Beta"),
        _folha_page(1, body="Anexo"),
        _folha_page(104, body="Delta"),
    )
    result = process(doc, policy="all_cheap", cheap=["text_layer"])
    assert [(p.folha.value, p.folha.in_sequence) for p in result.pages if p.folha] == [
        (101, True),
        (102, True),
        (1, False),
        (104, True),
    ]


def test_a_single_page_has_no_folha():
    doc = make_pdf(_folha_page(101))
    assert process(doc, policy="all_cheap", cheap=["text_layer"]).pages[0].folha is None


def test_lines_read_in_a_raster_say_which_raster_and_take_its_place_in_the_order():
    """A figura entre o texto de cima e o de baixo: as linhas dela ficam entre os dois."""
    doc = make_scanned_pdf(
        ["acima um", "acima dois"],
        render_mode=0,
        raster_box=(0.1, 0.4, 0.9, 0.6),
        text_y=780,
        text_lines_below=["abaixo um", "abaixo dois"],
        text_y_below=250,
    )
    result = process(doc, policy="all_cheap", cheap=["text_layer", _ReadsFigure()])
    assert len(result.pages[0].unread) == 1
    ordered = result.by_page()[0]
    assert [c.text for c in ordered] == [
        "acima um",
        "acima dois",
        "legenda na figura",
        "abaixo um",
        "abaixo dois",
    ]
    assert [c.reading_order for c in ordered] == [0, 1, 2, 3, 4]
    assert [c.region for c in ordered] == [None, None, 0, None, None]
    assert result.spent.regions_cheap == 1.0


def test_the_figure_of_a_composed_page_lists_its_lines_and_enters_the_annotated_text():
    """A figura sai de `unread` e de `region`, e o texto anotado diz que ela existe."""
    doc = make_scanned_pdf(
        ["acima um"],
        render_mode=0,
        raster_box=(0.1, 0.4, 0.9, 0.6),
        text_y=780,
        text_lines_below=["abaixo um"],
        text_y_below=250,
    )
    result = process(doc, policy="all_cheap", cheap=["text_layer", _ReadsFigure()])
    (figure,) = result.figures()
    caption = next(c for c in result.chunks if c.region == 0)
    assert (figure.ref, figure.page, figure.index) == ("p0:f0", 0, 0)
    assert figure.bbox == result.pages[0].unread[0]
    assert figure.chunk_ids == (caption.id,)
    assert "- figura p0:f0: 16% da página · 1 linha(s) lida(s): p0:1" in result.to_markdown(
        annotated=True
    )
    scanned = process(make_scanned_pdf(), policy="all_cheap", cheap=[FakeOCR()])
    assert scanned.figures() == [], "a folha digitalizada não é figura"


def test_figures_without_text_enter_the_annotated_text_as_one_count():
    """Uma página com imagens que nada leu: uma linha de contagem, não uma por imagem."""
    doc = make_scanned_pdf(
        ["acima um"],
        render_mode=0,
        raster_box=(0.1, 0.4, 0.9, 0.6),
        extra_raster_boxes=[(0.1, 0.05, 0.2, 0.1), (0.8, 0.05, 0.9, 0.1)],
        text_y=780,
    )
    result = process(doc, policy="all_cheap", cheap=["text_layer", _ReadsFigure()])
    assert len(result.figures()) == 3
    text = result.to_markdown(annotated=True)
    assert text.count("- figura ") == 1
    assert "- 2 imagem(ns) sem texto lido" in text


class _Says:
    """Leitor de pixels que devolve, por página, o texto combinado numa caixa fixa."""

    external = False
    output_version = "v1"

    def __init__(self, name: str, texts: dict[int, str]):
        self.name = name
        self.texts = texts
        self.calls = 0

    def read(self, view):
        self.calls += 1
        view.image()
        page = view.page
        text = self.texts.get(page.index, "")
        bbox = BBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
        if not text:
            return []
        return [
            Chunk(
                id=Chunk.make_id(Chunk.key_of(page), bbox, self.name, text, page=page.index),
                page=page.index,
                bbox=bbox,
                text=text,
                source=self.name,
                reading_order=0,
            )
        ]


def test_a_reader_of_another_family_confirms_or_fixes_before_the_costly_tier(scanned_doc):
    """Mesmo inválido nas duas famílias: erro do documento; válido no mesmo lugar: conserta."""
    cheap = _Says(
        "cheap",
        {
            0: "CPF 529.982.247-26",
            1: "CPF 529.982.247-26",
            2: "CPF 529.982.247-26",
            3: "",
            4: "texto limpo",
        },
    )
    other = _Says(
        "other",
        {0: "CPF 529.982.247-26", 1: "CPF 529.982.247-25", 2: "CPF 529.982.247-27", 3: "lido"},
    )
    vlm = FakeVLM()
    result = process(scanned_doc, policy="evidence", cheap=[cheap], confirm=other, strong=vlm)
    tiers = {d.page: d.tier for d in result.decisions}
    reasons = {d.page: d.reason for d in result.decisions}
    assert tiers[0] is Tier.CHEAP
    assert reasons[0].startswith("erro do documento: other")
    assert tiers[1] is Tier.CHEAP
    assert reasons[1] == "corrigido por other"
    assert tiers[2] is Tier.STRONG, "outro valor inválido: a página sobe"
    assert tiers[3] is Tier.STRONG, "leitura vazia não passa pela releitura"
    assert tiers[4] is Tier.CHEAP
    assert other.calls == 3, "só as páginas encaminhadas por verificação"
    assert vlm.calls == 2
    fixed = [c for c in result.chunks if c.page == 1]
    assert [c.text for c in fixed] == ["CPF 529.982.247-25"]
    assert fixed[0].source == "other"
    assert result.spent.pages_confirmed == 3.0
    assert result.spent.pages_confirmed_same == 1.0
    assert result.spent.pages_confirmed_fixed == 1.0
    others = {
        (o.reading.page, o.reading.source, o.reading.text, o.same, o.replaced)
        for o in result.others
    }
    assert others == {
        (0, "other", "CPF 529.982.247-26", True, False),
        (1, "cheap", "CPF 529.982.247-26", False, True),
        (2, "other", "CPF 529.982.247-27", False, False),
        (2, "fake-vlm", "vlm pagina 2", False, False),
    }, "a linha consertada na página 1 fica ao lado da que a substituiu"
    kept = {c.id for c in result.chunks}
    assert all(o.line in kept for o in result.others)
    assert all(o.reading.id not in kept for o in result.others if o.replaced)
    text = result.to_markdown(annotated=True)
    assert "- CPF: 529.982.247-26 · failed (impresso assim: other) · p0:0" in text
    printed = {e.page: e.printed for e in result.entities if e.kind == "CPF"}
    assert printed[0] == "other", "outra família leu o mesmo valor inválido"
    assert printed[2] is None, "a outra família leu outro valor: pode ser leitura"
    assert "- CPF: 529.982.247-26 · failed · p2:0" in text, "a outra família leu outro valor"


def test_a_rereading_fixes_an_amount_only_where_it_keeps_the_digits_the_cheap_reader_read(
    scanned_doc,
):
    """Valor em reais não tem redundância: outro dígito bem escrito no lugar não prova nada."""
    cheap = _Says("cheap", {0: "pagar R$ 1.O00,00", 1: "pagar R$ 1.O00,00"})
    other = _Says("other", {0: "pagar R$ 1.000,00", 1: "pagar R$ 7.000,00"})
    result = process(scanned_doc, policy="evidence", cheap=[cheap], confirm=other, strong=FakeVLM())
    decisions = {d.page: d for d in result.decisions}
    assert decisions[0].reason == "corrigido por other", "só a letra trocou de leitura"
    assert decisions[1].tier is Tier.STRONG, "o 1 virou 7: nenhum dos dois está provado"


def test_a_rereading_with_an_unproven_valid_value_fixes_only_where_it_keeps_the_digits(scanned_doc):
    """O CNPJ com letra confere sem prova: não conserta o dígito que a leitura barata leu."""
    cheap = _Says("cheap", {0: "CNPJ 18.236.120/0001-5B", 1: "CNPJ 18.236.120/0001-5B"})
    other = _Says("other", {0: "CNPJ 18.236.120/0001-58", 1: "CNPJ 18.S36.1S0/0001-58"})
    result = process(scanned_doc, policy="evidence", cheap=[cheap], confirm=other, strong=FakeVLM())
    decisions = {d.page: d for d in result.decisions}
    assert decisions[0].reason == "corrigido por other"
    assert decisions[1].tier is Tier.STRONG, "o 2 virou S: o verificador não vê"


class _MeteredSays(_Says):
    """O leitor de outra família como serviço pago: conta uma chamada por leitura."""

    def __init__(self, name: str, texts: dict[int, str]):
        super().__init__(name, texts)
        self.usage = {"calls": 0.0}

    def read(self, view):
        self.usage["calls"] += 1
        return super().read(view)


def test_what_the_rereading_reader_spends_is_in_spent(scanned_doc):
    """Um leitor pago em `confirm=` gasta; o gasto aparece, e uma vez só se é também o caro."""
    cheap = _Says("cheap", dict.fromkeys(range(5), "CPF 529.982.247-26"))
    other = _MeteredSays("other", dict.fromkeys(range(5), "CPF 529.982.247-26"))
    result = process(scanned_doc, policy="evidence", cheap=[cheap], confirm=other, strong=FakeVLM())
    assert result.spent.calls == 5.0, "as cinco releituras"

    both = _MeteredSays("both", dict.fromkeys(range(5), "CPF 529.982.247-26"))
    result = process(scanned_doc, policy="evidence", cheap=[cheap], confirm=both, strong=both)
    assert result.spent.calls == both.usage["calls"], "o mesmo leitor em dois papéis conta uma vez"


class _RecordingVLM(FakeVLM):
    """Guarda a view que recebeu em cada chamada."""

    def __init__(self, text: str | None = None):
        super().__init__(text=text)
        self.views = []

    def read(self, view):
        self.views.append(view)
        return super().read(view)


def test_escalate_by_region_hands_the_costly_reader_only_the_failing_lines(tmp_path):
    """O leitor caro recebe o recorte das linhas com valor inválido; as outras linhas ficam."""
    doc = make_scanned_pdf(["PODER JUDICIARIO", "CPF 529.982.247-27", "Valor R$ 10,00"])
    cheap_only = process(doc, policy="all_cheap", cheap=["text_layer"], trust_layer="always")
    failing = next(c for c in cheap_only.chunks if "CPF" in c.text)

    vlm = _RecordingVLM(text="CPF 529.982.247-25")
    cache = ModelCallCache(tmp_path / "c.sqlite")
    kwargs = {
        "policy": "evidence",
        "cheap": ["text_layer"],
        "strong": vlm,
        "cache": cache,
        "trust_layer": "always",
    }
    result = process(doc, reread="region", **kwargs)
    assert vlm.calls == 1
    view = vlm.views[0]
    assert isinstance(view, RegionView)
    assert view.box == failing.bbox, "o recorte é a caixa da linha"
    assert view.page.dimensions.width_px < cheap_only.pages[0].dimensions.width_px

    assert [c.source for c in result.chunks] == ["fake-vlm", "text_layer", "text_layer"]
    strong = result.chunks[0]
    assert (strong.bbox.x0, strong.bbox.y0, strong.bbox.x1, strong.bbox.y1) == pytest.approx(
        (failing.bbox.x0, failing.bbox.y0, failing.bbox.x1, failing.bbox.y1), abs=1e-3
    )
    assert strong.reading_order is None
    assert {c.text for c in result.chunks[1:]} == {"PODER JUDICIARIO", "Valor R$ 10,00"}
    assert result.spent.regions_strong == 1.0
    assert result.spent.pages_strong == 1.0
    [replaced] = result.others
    assert replaced.replaced
    assert (replaced.line, replaced.reading.id) == (strong.id, failing.id)

    again = process(doc, reread="region", **kwargs)
    assert vlm.calls == 1, "o recorte vem do cache"
    assert [c.id for c in again.chunks] == [c.id for c in result.chunks]
    cache.close()


def test_escalate_by_region_reads_both_lines_of_a_value_split_by_a_line_break():
    """`R$` no fim de uma linha e o número inválido na seguinte: o recorte cobre as duas."""
    doc = make_scanned_pdf(
        ["PODER JUDICIARIO", "o pagamento mensal de R$", "4.000,0o reais", "FIM"]
    )
    cheap_only = process(doc, policy="all_cheap", cheap=["text_layer"], trust_layer="always")
    split = [c for c in cheap_only.chunks if "R$" in c.text or "4.000" in c.text]
    assert len(split) == 2

    vlm = _RecordingVLM(text="o pagamento mensal de R$ 4.000,00 reais")
    result = process(
        doc,
        policy="evidence",
        cheap=["text_layer"],
        strong=vlm,
        reread="region",
        trust_layer="always",
    )
    assert vlm.calls == 1
    box = vlm.views[0].box
    assert box is not None
    assert box.y0 == pytest.approx(min(c.bbox.y0 for c in split))
    assert box.y1 == pytest.approx(max(c.bbox.y1 for c in split))
    assert result.spent.regions_strong == 1.0
    kept = {c.text for c in result.chunks if c.source == "text_layer"}
    assert kept == {"PODER JUDICIARIO", "FIM"}, "só as duas linhas do valor foram trocadas"


def test_escalate_by_region_still_reads_the_whole_page_when_nothing_points_to_a_line(
    scanned_doc,
):
    """Leitura vazia não aponta linha: a página vai inteira mesmo por região."""
    vlm = _RecordingVLM()
    result = process(scanned_doc, policy="evidence", cheap=[FakeOCR()], strong=vlm, reread="region")
    assert vlm.calls == 5
    assert not any(isinstance(v, RegionView) for v in vlm.views)
    assert result.spent.regions_strong == 0.0
    assert result.spent.pages_strong == 5.0


def test_escalate_by_page_is_the_default_and_hands_the_whole_page():
    doc = make_scanned_pdf(["CPF 529.982.247-27"])
    vlm = _RecordingVLM(text="CPF 529.982.247-25")
    result = process(doc, policy="evidence", cheap=["text_layer"], strong=vlm, trust_layer="always")
    assert not isinstance(vlm.views[0], RegionView)
    assert [c.source for c in result.chunks] == ["fake-vlm"]
    assert result.spent.regions_strong == 0.0


def test_escalate_by_region_reads_the_whole_page_when_a_signal_without_a_line_also_fired():
    """Um sinal que não aponta linha disparou junto: o recorte deixaria o resto da falha."""
    from docaudit.policies import CPF, EvidenceRouter, FailsCheck, signal

    doc = make_scanned_pdf(["PODER JUDICIARIO", "CPF 529.982.247-27"])
    policy = EvidenceRouter([signal("termo")(lambda page, chunks: 1), FailsCheck(CPF)])
    vlm = _RecordingVLM(text="CPF 529.982.247-25")
    result = process(
        doc, policy=policy, cheap=["text_layer"], strong=vlm, reread="region", trust_layer="always"
    )
    assert vlm.calls == 1
    assert not isinstance(vlm.views[0], RegionView)
    assert result.spent.regions_strong == 0.0
    assert [c.source for c in result.chunks] == ["fake-vlm"]


def test_two_families_reading_the_same_decimal_point_do_not_prove_it_printed(scanned_doc):
    """O ponto no lugar da vírgula decimal é troca que os leitores de pixels fazem juntos."""
    cheap = _Says(
        "cheap", {0: "total R$ 18.77", 1: "CPF 529.982.247-26", 2: "ok", 3: "ok", 4: "ok"}
    )
    other = _Says("other", {0: "total R$ 18.77", 1: "CPF 529.982.247-26"})
    vlm = FakeVLM()
    result = process(scanned_doc, policy="evidence", cheap=[cheap], confirm=other, strong=vlm)
    tiers = {d.page: d.tier for d in result.decisions}
    assert tiers[0] is Tier.STRONG, "o mesmo ponto lido duas vezes não encerra"
    assert tiers[1] is Tier.CHEAP, "o CPF lido igual continua provando o erro impresso"
    steps = result.decisions[0].steps
    assert "troca que as famílias fazem juntas" in steps[2]
    assert steps[3] == "nenhuma releitura explicou o valor; segue ao leitor caro"

    result = process(scanned_doc, policy="evidence", cheap=[cheap], confirm=other)
    printed = {e.page: e.printed for e in result.entities if e.state is EntityState.FAILED}
    assert printed == {0: None, 1: "other"}


def test_each_decision_tells_what_happened_to_the_page_in_order(scanned_doc):
    """Os passos saem na ordem: leitura barata, política, releitura, leitor caro."""
    cheap = _Says(
        "cheap", {0: "CPF 529.982.247-26", 1: "CPF 529.982.247-26", 2: "", 3: "ok", 4: "ok"}
    )
    other = _Says("other", {0: "CPF 529.982.247-26", 1: "CPF 529.982.247-25"})
    result = process(scanned_doc, policy="evidence", cheap=[cheap], confirm=other, strong=FakeVLM())
    steps = {d.page: d.steps for d in result.decisions}
    assert steps[0] == (
        "tier barato: cheap leu 1 linha(s)",
        "política: 1 x CPF que falha a verificação",
        "releitura por other: leu o mesmo valor inválido (529.982.247-26); "
        "o erro está impresso no documento, fica a leitura barata",
    )
    assert steps[1][2].startswith(
        "releitura por other: valor que confere no mesmo lugar; 1 linha(s)"
    )
    assert steps[2] == (
        "tier barato: ninguém leu nada",
        "política: 1 x leitura vazia",
        "fake-vlm leu a página inteira: 1 linha(s); substituiu 0 da leitura barata, ficaram 0",
    )
    assert steps[3] == ("tier barato: cheap leu 1 linha(s)", "política: sem evidência de falha")


def test_without_a_costly_reader_the_steps_say_so(scanned_doc):
    result = process(scanned_doc, policy="all_strong", cheap=[FakeOCR()])
    assert result.decisions[0].steps == (
        "política: política all_strong",
        "tier barato: fake-ocr leu 1 linha(s)",
        "sem leitor caro: fica a leitura barata",
    )


class _SecondBlockFirst:
    """Detector falso: o bloco das duas linhas de baixo vem antes do bloco da primeira."""

    output_version = "v1"

    def __init__(self):
        self.calls = 0

    def detect(self, image):
        self.calls += 1
        assert image
        return [
            Region(label="text", bbox=BBox(x0=0.0, y0=0.055, x1=1.0, y1=0.12)),
            Region(label="paragraph_title", bbox=BBox(x0=0.0, y0=0.0, x1=1.0, y1=0.055)),
        ]


class _SlowLayout(_SecondBlockFirst):
    """O detector que custa mais que a leitura da camada de texto."""

    def detect(self, image):
        time.sleep(0.01)
        return super().detect(image)


@pytest.mark.parametrize("workers", [1, 4])
def test_stage_seconds_are_never_negative_and_add_up_to_at_most_the_run(workers):
    """Com várias threads, a detecção de layout corre junto com a leitura, na mesma etapa."""
    doc = make_pdf(*[f"BT /F1 24 Tf 100 400 Td (pagina {i}) Tj ET" for i in range(8)])
    result = process(
        doc, policy="all_cheap", cheap=["text_layer"], layout=_SlowLayout(), workers=workers
    )
    stages = [result.spent.seconds_cheap, result.spent.seconds_confirm, result.spent.seconds_strong]
    assert all(s >= 0.0 for s in stages)
    assert sum(stages) <= result.spent.seconds
    assert result.spent.seconds_cheap >= 0.01, "a detecção conta na etapa barata"
    assert not hasattr(result.spent, "seconds_layout")


def test_layout_reorders_what_every_reader_read_and_is_cached(tmp_path):
    """Três linhas da camada de texto; o detector manda as duas últimas antes da primeira."""
    doc = make_scanned_pdf(["ALTO UM", "ALTO DOIS", "EMBAIXO"], text_y=800)
    layout = _SecondBlockFirst()
    cache = ModelCallCache(tmp_path / "c.sqlite")
    result = process(
        doc,
        policy="all_cheap",
        cheap=["text_layer"],
        layout=layout,
        cache=cache,
        trust_layer="always",
    )
    assert [c.text for c in result.chunks] == ["ALTO DOIS", "EMBAIXO", "ALTO UM"]
    assert [c.reading_order for c in result.chunks] == [0, 1, 2]
    assert [c.kind for c in result.chunks] == ["text", "text", "paragraph_title"]
    assert result.decisions[0].steps[-1] == "layout: 2 bloco(s), linhas na ordem dos blocos"
    assert layout.calls == 1

    again = process(
        doc,
        policy="all_cheap",
        cheap=["text_layer"],
        layout=layout,
        cache=cache,
        trust_layer="always",
    )
    assert layout.calls == 1, "as regiões vêm do cache"
    assert again.spent.pages_layout_cached == 1.0
    assert [c.id for c in again.chunks] == [c.id for c in result.chunks]
    cache.close()


# ── Os elementos fixos da página ───────────────────────────────────────────────────────


def _page_with_furniture(number: int, signer: str) -> str:
    """Cabeçalho e rodapé iguais em toda página, um número de folha, e um corpo próprio."""
    return "\n".join(
        [
            f"BT /F1 8 Tf 500 815 Td ({number}) Tj ET",
            "BT /F1 10 Tf 70 800 Td (TRIBUNAL DE JUSTICA DO ESTADO) Tj ET",
            "BT /F1 10 Tf 70 786 Td (Comarca da Capital) Tj ET",
            f"BT /F1 10 Tf 70 600 Td (Corpo proprio desta folha, assunto {signer}) Tj ET",
            "BT /F1 10 Tf 70 500 Td (Recebido em:) Tj ET",
            f"BT /F1 10 Tf 70 120 Td (Assinado por {signer}) Tj ET",
            f"BT /F1 10 Tf 70 40 Td (Pagina {number} de 3) Tj ET",
        ]
    )


def test_lines_repeated_in_place_from_the_edge_are_furniture_and_the_body_is_not():
    """O cabeçalho e o rodapé repetidos ficam marcados; o número da folha, o corpo, o rótulo
    repetido no meio da página e a assinatura própria de cada página, não."""
    doc = make_pdf(
        *(_page_with_furniture(n, s) for n, s in ((1, "Alfa"), (2, "Beta"), (3, "Gama")))
    )
    result = process(doc, policy="all_cheap", cheap=["text_layer"])
    furniture = sorted({c.text for c in result.chunks if c.furniture})
    assert furniture == [
        "Comarca da Capital",
        "Pagina 1 de 3",
        "Pagina 2 de 3",
        "Pagina 3 de 3",
        "TRIBUNAL DE JUSTICA DO ESTADO",
    ]
    kept = {c.text for c in result.chunks if not c.furniture}
    assert {
        "1",
        "Recebido em:",
        "Assinado por Beta",
        "Corpo proprio desta folha, assunto Beta",
    } <= kept
    body = result.to_markdown(furniture=False)
    assert "TRIBUNAL" not in body
    assert "assunto Beta" in body
    assert "TRIBUNAL" in result.to_markdown(), "a marca não apaga a linha"


def test_a_single_page_has_no_furniture():
    doc = make_pdf(_page_with_furniture(1, "Alfa"))
    assert not any(
        c.furniture for c in process(doc, policy="all_cheap", cheap=["text_layer"]).chunks
    )


def _read_box(y0: float, turn: Literal[0, 90, 270]) -> BBox:
    """A caixa de uma linha larga à altura `y0` da leitura, no sistema da imagem."""
    return BBox(x0=0.1, y0=y0, x1=0.9, y1=y0 + 0.02).unturned(turn)


def _line(page: int, text: str, y0: float, turn: Literal[0, 90, 270]) -> Chunk:
    return Chunk.make(make_page(page), _read_box(y0, turn), "ocr", text, turn=turn)


@pytest.mark.parametrize("turn", [90, 270])
def test_a_page_read_sideways_marks_furniture_as_read_and_not_as_scanned(turn):
    """O cabeçalho e o rodapé repetidos ficam marcados; o rótulo repetido no meio da leitura, não.

    Na imagem, toda linha dessa página é alta, e parece a tarja da margem.
    """
    pages = {
        page: [
            _line(page, "TRIBUNAL DE JUSTICA", 0.05, turn),
            _line(page, f"Corpo proprio {name}", 0.3, turn),
            _line(page, "Recebido em:", 0.5, turn),
            _line(page, f"Assinado por {name}", 0.7, turn),
            _line(page, "Comarca da Capital", 0.95, turn),
        ]
        for page, name in enumerate(("Alfa", "Beta"))
    }
    assert _marked(pages)[0] == {"TRIBUNAL DE JUSTICA", "Comarca da Capital"}


def test_a_line_of_the_layer_stays_at_its_edge_on_a_page_read_sideways():
    """A linha própria no alto da leitura girada não interrompe a tarja no alto da camada."""
    pages = {
        page: [
            _line(page, f"Linha propria {name}", 0.01, 90),
            _line(page, "Tarja da camada", 0.03, 0),
        ]
        for page, name in enumerate(("Alfa", "Beta"))
    }
    assert _marked(pages)[0] == {"Tarja da camada"}


def _statement(page: int, names: Sequence[str]) -> list[Chunk]:
    """Uma folha de demonstrativo: cabeçalho, título, uma linha por nome e o rodapé."""
    return [
        _line(page, "TRIBUNAL DE JUSTICA", 0.02, 0),
        _line(page, "Demonstrativo do calculo", 0.1, 0),
        *(_line(page, f"Credor {name}", 0.3 + 0.05 * i, 0) for i, name in enumerate(names)),
        _line(page, f"Pagina {page + 1}", 0.95, 0),
    ]


def _marked(pages: Mapping[int, Sequence[Chunk]]) -> dict[int, set[str]]:
    return {p: {c.text for c in cs if c.furniture} for p, cs in mark_furniture(pages).items()}


_MARGIN = BBox(x0=0.96, y0=0.1, x1=0.98, y1=0.9)
_FIRST, _SECOND = ("Alfa", "Beta", "Gama"), ("Delta", "Epsilon", "Zeta")


def test_a_page_repeated_in_the_file_keeps_its_body():
    """A página e a cópia não provam o elemento fixo uma da outra, nem com a margem diferente."""
    signers = ("Alfa", "Beta", "Gama", "Delta")
    pages = {
        p: [
            *_statement(p, (_FIRST, _SECOND)[p % 2]),
            Chunk.make(make_page(p), _MARGIN, "ocr", f"Assinado por {signers[p]}"),
        ]
        for p in range(4)
    }
    for page, marked in _marked(pages).items():
        assert marked == {"TRIBUNAL DE JUSTICA", "Demonstrativo do calculo", f"Pagina {page + 1}"}


def test_pages_that_are_all_copies_of_each_other_keep_their_furniture():
    """Sem página diferente, a cópia não se reconhece: a peça só de anexos fica com a folha."""
    pages = {
        p: [_line(p, "TRIBUNAL DE JUSTICA", 0.02, 0), _line(p, f"fls. {p + 10}", 0.95, 0)]
        for p in range(3)
    }
    assert _marked(pages) == {p: {"TRIBUNAL DE JUSTICA", f"fls. {p + 10}"} for p in range(3)}


def test_pages_with_only_the_margin_strip_still_mark_it():
    """Duas páginas sem linha horizontal com letra não são cópia uma da outra."""
    pages = {p: [Chunk.make(make_page(p), _MARGIN, "ocr", "Assinado por Alfa")] for p in range(2)}
    assert _marked(pages) == {0: {"Assinado por Alfa"}, 1: {"Assinado por Alfa"}}


def test_a_blank_page_keeps_its_furniture():
    """A folha só com cabeçalho e rodapé está contida nas outras, e continua marcada."""
    pages = {0: _statement(0, _FIRST), 1: _statement(1, ()), 2: _statement(2, _SECOND)}
    assert _marked(pages)[1] == {"TRIBUNAL DE JUSTICA", "Demonstrativo do calculo", "Pagina 2"}


# ── A leitura cara passa pelas mesmas verificações ───────────────────────────


def _strong_outcome(cheap_text: str, strong_text: str, policy, scanned_doc):
    cheap = _Says("cheap", {0: cheap_text})
    strong = _Says("strong", {0: strong_text})
    return process(scanned_doc, cheap=[cheap], strong=strong, policy=policy, pages={0})


def test_a_costly_line_that_loses_a_valid_value_is_refused_and_the_cheap_line_stays(scanned_doc):
    """Consertou o valor que falhou, mas perdeu o CPF que conferia: não entra."""
    result = _strong_outcome(
        "CPF 529.982.247-25 e valor R$ 1,170,00", "valor R$ 1.170,00", "evidence", scanned_doc
    )
    assert [c.source for c in result.chunks] == ["cheap"]
    assert result.spent.lines_strong_rejected == 1
    assert any("perdeu CPF" in s for s in result.decisions[0].steps)


def test_a_refused_costly_line_with_another_amount_is_a_doubt_beside_the_cheap_line(scanned_doc):
    """Dois valores bem escritos e diferentes: fica a barata, e a cara fica ao lado como dúvida."""
    from docaudit import Document
    from docaudit.policies import AllStrong

    class ReadThenStrong(AllStrong):
        needs_reads = True

    result = _strong_outcome(
        "Valor da causa R$ 1.284,56", "Valor da causa R$ 1.234,56", ReadThenStrong(), scanned_doc
    )
    assert [c.source for c in result.chunks] == ["cheap"]
    (other,) = result.others
    assert (other.reading.source, other.same, other.replaced) == ("strong", False, False)
    assert (other.check, other.value) == ("valor em reais", "1.284,56")
    with Document(scanned_doc) as session:
        (doubt,) = session.doubts(result)
    assert (doubt.chunk.id, doubt.check, doubt.value) == (
        result.chunks[0].id,
        "valor em reais",
        "1.284,56",
    )


def test_a_refused_costly_line_with_another_valid_id_names_the_field_and_the_printed_value(
    scanned_doc,
):
    """A dúvida traz o nome do campo e o valor como a linha barata o imprime."""
    from docaudit.policies import CPF, AllStrong, FailsCheck

    class ReadThenStrong(AllStrong):
        needs_reads = True
        checks = (FailsCheck(CPF),)

    result = _strong_outcome(
        "CPF 529.982.247-25", "CPF 111.444.777-35", ReadThenStrong(), scanned_doc
    )
    assert [c.source for c in result.chunks] == ["cheap"]
    (other,) = result.others
    assert (other.check, other.value) == ("CPF", "529.982.247-25")


def test_a_refused_costly_line_beside_a_failing_line_is_listed_once(scanned_doc):
    """Na linha que falha, a dúvida já existe: a linha cara fica ao lado uma vez, sem `check`."""
    result = _strong_outcome(
        "CPF 529.982.247-26 valor R$ 1.284,56",
        "CPF 529.982.247-25 valor R$ 1.234,56",
        "evidence",
        scanned_doc,
    )
    assert [c.source for c in result.chunks] == ["cheap"]
    (other,) = result.others
    assert (other.reading.source, other.check, other.value) == ("strong", None, None)


def test_a_costly_line_that_reads_the_decimal_comma_as_a_point_is_refused(scanned_doc):
    """Na tabela, o R$ fica na linha de cima: o valor sem símbolo também conta."""
    result = _strong_outcome(
        "CPF 529.982.247-26 15.062,39", "CPF 529.982.247-25 15.062.39", "evidence", scanned_doc
    )
    assert [c.source for c in result.chunks] == ["cheap"]
    assert any("vírgula decimal" in s for s in result.decisions[0].steps)


def test_the_same_invalid_value_in_the_costly_read_does_not_prove_a_printed_error(scanned_doc):
    """O leitor caro não é declarado de outra família: o padrão é o mesmo PP-OCR."""
    result = _strong_outcome("CPF 529.982.247-26", "CPF 529.982.247-26", "evidence", scanned_doc)
    assert [c.source for c in result.chunks] == ["cheap"]
    assert any("leu o mesmo valor inválido" in s for s in result.decisions[0].steps)
    assert not any("erro do documento" in s for s in result.decisions[0].steps)
    [cpf] = result.entities
    assert cpf.state is EntityState.FAILED
    assert cpf.printed is None


def test_a_valid_value_in_place_from_the_costly_read_replaces_the_cheap_line(scanned_doc):
    result = _strong_outcome("CPF 529.982.247-26", "CPF 529.982.247-25", "evidence", scanned_doc)
    assert [c.source for c in result.chunks] == ["strong"]
    assert result.spent.lines_strong_rejected == 0
    [replaced] = result.others
    assert replaced.replaced
    assert not replaced.same
    assert replaced.line == result.chunks[0].id
    assert (replaced.reading.source, replaced.reading.text) == ("cheap", "CPF 529.982.247-26")


def test_a_costly_line_with_the_same_text_leaves_no_replaced_reading(scanned_doc):
    """A linha relida com o mesmo texto não vai para `others`."""
    result = _strong_outcome("texto limpo", "texto limpo", "all_strong", scanned_doc)
    assert [c.source for c in result.chunks] == ["strong"]
    assert result.others == ()


def test_a_costly_read_with_the_comma_and_the_same_digits_repairs_a_bare_amount(scanned_doc):
    """Sem `R$` na linha, a vírgula no lugar do ponto, com os mesmos dígitos, explica a falha."""
    result = _strong_outcome("15.062.39", "15.062,39", "evidence", scanned_doc)
    assert [c.source for c in result.chunks] == ["strong"]
    assert result.spent.lines_strong_rejected == 0


def test_a_renamed_amount_check_keeps_the_bare_amount_rule(scanned_doc):
    """A cópia de `AMOUNT_BRL` com outro nome conserta o valor sem `R$` como o original."""
    import dataclasses

    from docaudit.policies import AMOUNT_BRL, EvidenceRouter, FailsCheck

    valor = dataclasses.replace(AMOUNT_BRL, name="valor")
    policy = EvidenceRouter([FailsCheck(valor)])
    result = _strong_outcome("15.062.39", "15.062,39", policy, scanned_doc)
    assert [c.source for c in result.chunks] == ["strong"]
    assert result.spent.lines_strong_rejected == 0


def test_without_an_amount_check_a_bare_amount_refuses_nothing(scanned_doc):
    """Sem verificação de valor em reais pedida, o número com vírgula não segura a linha barata."""
    from docaudit.policies import AllStrong

    class ReadThenStrong(AllStrong):
        needs_reads = True

    cheap = _Says("cheap", {0: "Valor da causa R$ 1.284,56"})
    strong = _Says("strong", {0: "Valor da causa R$ 1.234,56"})
    result = process(
        scanned_doc, cheap=[cheap], strong=strong, policy=ReadThenStrong(), entities=[CPF]
    )
    assert [c.source for c in result.chunks] == ["strong"]
    assert result.spent.lines_strong_rejected == 0


def test_a_costly_read_with_other_digits_does_not_repair_a_bare_amount(scanned_doc):
    result = _strong_outcome("15.062.39", "15.062,89", "evidence", scanned_doc)
    assert [c.source for c in result.chunks] == ["cheap"]
    assert any("não explicou" in s for s in result.decisions[0].steps)


def test_a_costly_read_that_explains_nothing_is_refused(scanned_doc):
    result = _strong_outcome("CPF 529.982.247-26", "texto sem o valor", "evidence", scanned_doc)
    assert [c.source for c in result.chunks] == ["cheap"]
    assert any("não explicou" in s for s in result.decisions[0].steps)


class _OverLayer:
    """Leitor de pixels que devolve as linhas da camada oculta no lugar delas, trocando textos."""

    external = False
    output_version = "v1"
    name = "pixels"

    def __init__(self, swaps: dict[str, str]):
        self.swaps = swaps

    def read(self, view):
        view.image()
        return [
            Chunk.make(view.page, line.bbox, self.name, self.swaps.get(line.text) or line.text)
            for line in view.text_lines()
        ]


def test_the_hidden_layer_reading_another_amount_is_a_doubt_and_the_reading_stays():
    """O valor em reais não tem dígito: a camada oculta que lê outro número aponta a linha."""
    from docaudit import Document

    doc = make_scanned_pdf(["Total R$ 1.234,56", "Saldo R$ 10,00", "Processo encerrado"])
    reader = _OverLayer({"Total R$ 1.234,56": "Total R$ 1.284,56"})
    with Document(doc, cheap=[reader]) as session:
        result = session.read(policy="all_cheap")
        assert [c.text for c in result.chunks] == [
            "Total R$ 1.284,56",
            "Saldo R$ 10,00",
            "Processo encerrado",
        ], "a leitura não muda"
        (other,) = result.others
        assert (other.reading.text, other.same) == ("Total R$ 1.234,56", False)
        (doubt,) = session.doubts(result)
        assert (doubt.check, doubt.value, doubt.chunk.text) == (
            "valor em reais",
            "1.284,56",
            "Total R$ 1.284,56",
        )
    trusted = process(doc, cheap=["text_layer", reader], trust_layer="always")
    assert trusted.others == (), "com a camada como leitura, não há outra família"
    unchecked = process(doc, cheap=[reader], policy="all_cheap", entities=[CPF])
    assert unchecked.others == (), "sem verificação de valor em reais, não há o que comparar"


def test_a_confirmed_id_only_the_hidden_layer_read_takes_the_place_of_the_pixel_line():
    """O id que confere na camada e que os pixels leram errado troca a linha dos pixels."""
    cpf, cnj = "CPF 529.982.247-25", "Processo 9001087-60.2022.8.26.0390"
    doc = make_scanned_pdf([cpf, cnj, "Total R$ 1.234,56"])
    reader = _OverLayer({cpf: "CPF 529.982.247-2S", "Total R$ 1.234,56": "Total ilegivel"})
    result = process(doc, policy="all_cheap", cheap=[reader])
    assert [(c.text, c.source) for c in result.chunks] == [
        (cpf, "text_layer"),
        (cnj, "pixels"),
        ("Total ilegivel", "pixels"),
    ], "no lugar da linha errada, uma vez; o valor sem dígito fica com os pixels"
    assert [c.reading_order for c in result.chunks] == [0, 1, 2]
    (swap,) = [o for o in result.others if o.replaced]
    assert (swap.line, swap.reading.text) == (result.chunks[0].id, "CPF 529.982.247-2S")
    confirmed = {e.kind for e in result.entities if e.state.value == "confirmed"}
    assert {"CPF", "CNJ"} <= confirmed
    assert any("no lugar de 1 linha" in s for s in result.decisions[0].steps)
    trusted = process(doc, policy="all_cheap", cheap=["text_layer", reader], trust_layer="always")
    assert not any(o.replaced for o in trusted.others), "a camada já é a leitura"


def test_a_layer_value_without_proof_does_not_take_the_place_of_the_pixel_line():
    """O CNPJ com letra e a data com dia da semana conferem sem prova: a linha dos pixels fica."""
    cnpj, date = "CNPJ 18.S36.1S0/0001-58", "segunda-feira, 17/03/2025"
    doc = make_scanned_pdf([cnpj, date])
    reader = _OverLayer({cnpj: "CNPJ 18.236.120/0001-58", date: "segunda-feira, 10/03/2025"})
    result = process(doc, policy="all_cheap", cheap=[reader])
    assert [(c.text, c.source) for c in result.chunks] == [
        ("CNPJ 18.236.120/0001-58", "pixels"),
        ("segunda-feira, 10/03/2025", "pixels"),
    ]


def test_a_short_layer_line_inside_a_wide_pixel_line_does_not_erase_it():
    """A folha da camada dentro do cabeçalho lido pelos pixels entra ao lado, e o cabeçalho fica."""
    (page,) = load_pages(make_scanned_pdf(["x"]))
    header = Chunk.make(
        page, BBox(x0=0.05, y0=0.02, x1=0.95, y1=0.05), "pixels", "PODER JUDICIARIO fls. 103"
    )
    fls = Chunk.make(page, BBox(x0=0.45, y0=0.02, x1=0.55, y1=0.05), "text_layer", "fls. 103")
    out, others = _in_place_of_pixels(page, [header], [fls], [])
    assert [c.text for c in out] == ["fls. 103", "PODER JUDICIARIO fls. 103"]
    assert others == []
    narrow = header.model_copy(update={"bbox": BBox(x0=0.46, y0=0.02, x1=0.54, y1=0.05)})
    out, others = _in_place_of_pixels(page, [narrow], [fls], [])
    assert [c.text for c in out] == ["fls. 103"], "a linha dos pixels que a da camada cobre sai"
    assert [o.reading.text for o in others] == ["PODER JUDICIARIO fls. 103"]


def test_layer_lines_with_no_pixel_line_under_them_keep_their_own_order():
    """As colunas da tarja na vertical, sem leitura dos pixels, entram na ordem em que casaram."""
    (page,) = load_pages(make_scanned_pdf(["x"]))
    body = Chunk.make(page, BBox(x0=0.1, y0=0.5, x1=0.8, y1=0.52), "pixels", "corpo")
    first = Chunk.make(page, BBox(x0=0.95, y0=0.1, x1=0.97, y1=0.9), "text_layer", "um")
    second = Chunk.make(page, BBox(x0=0.97, y0=0.1, x1=0.99, y1=0.9), "text_layer", "dois")
    out, _ = _in_place_of_pixels(page, [body], [second, first], [])
    assert [c.text for c in out] == ["dois", "um", "corpo"]
    assert [c.reading_order for c in out] == [0, 1, 2]


def test_spans_say_where_each_value_is_in_its_lines_only_when_asked():
    """Com `spans`, o valor sai com começo e fim no texto das linhas dele, também quando quebra."""
    doc = make_pdf(_stamped("Requerente CPF 529.982.247-25 e valor R$", "4.000,00 a receber"))
    plain = process(doc, policy="all_cheap", cheap=["text_layer"])
    assert all(e.span is None for e in plain.entities), "desligado por omissão"
    result = process(doc, policy="all_cheap", cheap=["text_layer"], spans=True)
    lines = {c.id: c.text for c in result.chunks}
    assert result.run is not None
    assert result.run.spans
    for entity in result.entities:
        assert entity.span is not None
        start, end = entity.span
        text = "\n".join(lines[i] for i in entity.chunk_ids)
        assert " ".join(text[start:end].split()) == entity.value
    amount = next(e for e in result.entities if e.kind == "valor em reais")
    assert len(amount.chunk_ids) == 2, "o valor que quebra entre linhas"


def test_the_stamp_drawn_in_sight_over_a_scan_is_read_from_the_layer():
    """A camada da digitalização não é a leitura, mas a tarja à vista por cima dela é texto
    exato: entra no lugar do que os pixels leram ali."""
    strip = _strip(_OWN, "AbCd1234")
    body = ["corpo da peticao", "segunda linha", "terceira linha", "quarta linha", "quinta linha"]
    doc = make_scanned_pdf(body, stamped=strip)
    reader = _OverLayer({strip[0]: "Este documento e copla do orlginal", strip[1]: "Para confenr"})
    result = process(doc, policy="all_cheap", cheap=[reader])
    assert result.pages[0].substrate.value == "searchable_scan"
    assert result.pages[0].stamp is not None
    assert result.pages[0].stamp.code == "AbCd1234"
    layer = [c.text for c in result.chunks if c.source == "text_layer"]
    assert layer == list(strip), "só a tarja vem da camada; o corpo segue dos pixels"
    assert "corpo da peticao" in [c.text for c in result.chunks if c.source == "pixels"]


class _SidewaysOCR(FakeOCR):
    """Uma leitura barata de página de lado, com um CPF inválido entre as linhas."""

    name = "ocr"

    def __init__(self, turn: Literal[90, 270]):
        super().__init__()
        self.turn: Literal[90, 270] = turn

    def read(self, view):
        self.calls += 1
        view.image()
        return [
            Chunk.make(
                view.page,
                _read_box(y0, self.turn),
                self.name,
                text,
                reading_order=i,
                turn=self.turn,
            )
            for i, (text, y0) in enumerate((("CPF 529.982.247-27", 0.2), ("Valor R$ 10,00", 0.4)))
        ]


@pytest.mark.parametrize("turn", [90, 270])
@pytest.mark.parametrize("reread", ["region", "page"])
def test_a_page_read_sideways_is_reread_upright_and_the_line_keeps_the_turn(reread, turn, tmp_path):
    """O leitor caro vê o que a barata viu em pé, e a caixa da linha volta ao sistema da imagem."""
    doc = make_scanned_pdf(pixels=(600, 800))
    vlm = _RecordingVLM(text="CPF 529.982.247-25 Valor R$ 10,00")
    cache = ModelCallCache(tmp_path / "c.sqlite")
    kwargs = {"policy": "evidence", "cheap": [_SidewaysOCR(turn)], "strong": vlm, "cache": cache}
    result = process(doc, reread=reread, **kwargs)

    assert vlm.calls == 1
    dimensions = vlm.views[0].page.dimensions
    assert dimensions.width_px > dimensions.height_px, "o recorte e a página chegam em pé"
    strong = next(c for c in result.chunks if c.source == vlm.name)
    assert strong.turn == turn
    if reread == "region":
        expected = _read_box(0.2, turn)
        assert strong.bbox.x1 - strong.bbox.x0 < strong.bbox.y1 - strong.bbox.y0
        assert strong.bbox.intersection(expected) == pytest.approx(expected.area, rel=0.1)
        assert strong.reading_order is None
    else:
        assert strong.reading_order == 0, "a página inteira tem a ordem do leitor"

    again = process(doc, reread=reread, **kwargs)
    assert vlm.calls == 1, "a releitura em pé vem do cache"
    assert [c.id for c in again.chunks] == [c.id for c in result.chunks]
    cache.close()


def test_a_page_read_upright_is_reread_as_it_is():
    """Sem giro, a releitura vê a própria página: a vista dela, e não um recorte."""
    doc = make_scanned_pdf(["CPF 529.982.247-27"])
    vlm = _RecordingVLM(text="CPF 529.982.247-25")
    process(doc, policy="evidence", cheap=["text_layer"], strong=vlm, trust_layer="always")
    assert not isinstance(vlm.views[0], RegionView)


def test_the_time_cap_leaves_the_pages_it_reaches_with_the_cheap_read(scanned_doc):
    """Cinco páginas escaladas, um teto já vencido: nenhuma vai ao leitor caro, e a decisão fica."""
    vlm = FakeVLM()
    result = process(
        scanned_doc,
        policy="evidence",
        budget=Budget(max_seconds=1e-9),
        cheap=[FakeOCR()],
        strong=vlm,
    )
    assert vlm.calls == 0
    assert result.spent.pages_strong == 0
    assert sum(d.tier is Tier.STRONG for d in result.decisions) == 5, "o veredito da política fica"
    assert all("teto de tempo" in d.steps[-1] for d in result.decisions if d.tier is Tier.STRONG)
    assert result.run is not None
    assert result.run.budget.max_seconds == 1e-9


def test_a_page_the_time_cap_deferred_still_gets_its_cheap_read(scanned_doc):
    """`all_strong` dispensa a leitura barata; com o teto vencido, a página ainda vai ao barato."""
    vlm = FakeVLM()
    result = process(
        scanned_doc,
        policy="all_strong",
        budget=Budget(max_seconds=1e-9),
        cheap=[FakeOCR()],
        strong=vlm,
    )
    assert vlm.calls == 0
    assert result.spent.pages_strong == 0
    assert result.spent.pages_cheap == 5
    assert {c.source for c in result.chunks} == {FakeOCR.name}
    assert not any(d.incomplete for d in result.decisions)


def test_a_raster_floor_outside_the_unit_interval_is_refused(scanned_doc):
    with pytest.raises(ValueError, match="min_raster_fraction"):
        process(scanned_doc, min_raster_fraction=1.5)


def test_without_a_time_cap_every_escalated_page_is_read(scanned_doc):
    vlm = FakeVLM()
    process(
        scanned_doc,
        policy="evidence",
        budget=Budget(max_seconds=3600),
        cheap=[FakeOCR()],
        strong=vlm,
    )
    assert vlm.calls == 5


def test_a_raster_below_the_floor_is_not_sent_to_the_pixel_reader():
    """O logotipo fica em `Page.unread`, sem linha; a página fica com a camada numa leitura só."""
    reader = _SeesTheCrop()
    doc = make_scanned_pdf(["acima"], render_mode=0, raster_box=(0.1, 0.4, 0.3, 0.5), text_y=780)

    result = process(
        doc, policy="all_cheap", cheap=["text_layer", reader], min_raster_fraction=0.05
    )

    assert reader.seen == [], "o recorte abaixo do piso não é lido"
    assert [c.source for c in result.chunks] == ["text_layer"]
    assert len(result.pages[0].unread) == 1, "o raster continua declarado"
    assert result.run is not None
    assert result.run.min_raster_fraction == 0.05


def test_the_default_floor_reads_every_raster():
    reader = _SeesTheCrop()
    doc = make_scanned_pdf(["acima"], render_mode=0, raster_box=(0.1, 0.4, 0.3, 0.5), text_y=780)
    process(doc, policy="all_cheap", cheap=["text_layer", reader])
    assert len(reader.seen) == 1


def test_a_stamp_format_with_a_timezone_gives_an_aware_time():
    from dataclasses import replace
    from zoneinfo import ZoneInfo

    with_tz = replace(ESAJ_STAMP, tz="America/Sao_Paulo")
    doc = make_pdf(_stamped("Peticao inicial", *_strip(_OWN, "AbCd1234")))

    naive = process(doc, policy="all_cheap", cheap=["text_layer"]).pages[0].stamp
    aware = process(doc, policy="all_cheap", cheap=["text_layer"], stamps=[with_tz]).pages[0].stamp

    assert naive is not None
    assert aware is not None
    assert naive.at is not None
    assert aware.at is not None
    assert naive.at.tzinfo is None
    assert aware.at.tzinfo == ZoneInfo("America/Sao_Paulo")
    assert aware.at.replace(tzinfo=None) == naive.at, "a hora impressa é a mesma; só o fuso entra"


def test_an_unknown_timezone_is_refused_when_the_format_is_built():
    from dataclasses import replace

    with pytest.raises(ValueError, match="fuso"):
        replace(ESAJ_STAMP, tz="Brasil/Capital")


def test_pieces_group_consecutive_pages_by_stamp_code():
    doc = make_pdf(
        _stamped("Peticao inicial", *_strip(_OWN, "AbCd1234")),
        _stamped("Pagina dois da peticao", *_strip(_OWN, "AbCd1234")),
        _stamped("Documento", *_strip(_OWN, "EfGh5678")),
        _stamped("Folha sem tarja"),
        _stamped("Outra folha sem tarja"),
        _stamped("Decisao", *_strip(_OWN, "AbCd1234")),
    )
    result = process(doc, policy="all_cheap", cheap=["text_layer"])
    pieces = result.pieces()

    assert [(p.code, p.pages) for p in pieces] == [
        ("AbCd1234", (0, 1)),
        ("EfGh5678", (2,)),
        (None, (3, 4)),
        ("AbCd1234", (5,)),
    ]
    assert [p.index for p in pieces] == [0, 1, 2, 3]
    assert pieces[0].stamp is not None
    assert pieces[0].stamp.code == "AbCd1234"
    assert pieces[2].stamp is None


class _Boxes:
    """Um leitor que devolve linhas com as caixas dadas, como um OCR as detecta."""

    name = "boxes"
    external = False
    output_version = "1"

    def __init__(self, lines: list[tuple[str, tuple[float, float, float, float]]]) -> None:
        self.lines = lines

    def read(self, view):
        return [
            Chunk.make(
                view.page, BBox(x0=x0, y0=y0, x1=x1, y1=y1), self.name, text, reading_order=n
            )
            for n, (text, (x0, y0, x1, y1)) in enumerate(self.lines)
        ]


def test_records_group_lines_into_rows_and_blocks_by_geometry():
    """Duas células na mesma altura são uma fileira; um vão maior que a entrelinha separa blocos."""
    reader = _Boxes(
        [
            ("Nome", (0.10, 0.100, 0.30, 0.115)),
            ("Valor", (0.50, 0.101, 0.70, 0.116)),
            ("ALFA LTDA", (0.10, 0.120, 0.30, 0.135)),
            ("R$ 10,00", (0.50, 0.120, 0.70, 0.135)),
            ("Paragrafo isolado, uma linha so.", (0.10, 0.300, 0.80, 0.315)),
            ("Segunda linha do paragrafo.", (0.10, 0.320, 0.60, 0.335)),
        ]
    )
    result = process(make_scanned_pdf(), policy="all_cheap", cheap=[reader])
    records = result.records()

    assert [r.rows for r in records] == [
        (("Nome", "Valor"), ("ALFA LTDA", "R$ 10,00")),
        (("Paragrafo isolado, uma linha so.",), ("Segunda linha do paragrafo.",)),
    ]
    assert [r.ref for r in records] == ["p0:b0", "p0:b1"]
    assert [r.tabular for r in records] == [True, False]
    assert records[0].text == "Nome | Valor\nALFA LTDA | R$ 10,00"
    assert len(records[0].chunk_ids) == 4
    assert records[0].bbox.y1 <= records[1].bbox.y0, "os blocos saem de cima para baixo"
    assert len(result.records(gap=100.0)) == 1, "um vão folgado junta a página num bloco"


def test_each_decision_carries_the_seconds_of_the_stages_that_touched_its_page(scanned_doc):
    vlm = FakeVLM()
    result = process(scanned_doc, policy="evidence", cheap=[FakeOCR()], strong=vlm)
    for decision in result.decisions:
        assert decision.seconds["cheap"] >= 0.0
        assert ("strong" in decision.seconds) == (decision.tier is Tier.STRONG)
    assert "confirm" not in result.decisions[0].seconds, "sem confirm= nem camada, a etapa não toca"


def _merged_cell_table(cell: bool):
    """Seis credores com valor, cada um numa fileira; com `cell`, uma categoria mesclada ao lado."""
    lines = [("MATERIA PRIMA", (0.01, 0.30, 0.04, 0.38))] if cell else []
    for i in range(6):
        y = 0.30 + i * 0.0125
        lines += [
            (f"CREDOR {i}", (0.05, y, 0.30, y + 0.012)),
            (f"{i}.000,00", (0.80, y, 0.95, y + 0.012)),
        ]
    return process(make_scanned_pdf(), policy="all_cheap", cheap=[_Boxes(lines)])


def test_a_merged_cell_does_not_chain_the_rows_it_spans():
    rows = [row for record in _merged_cell_table(cell=True).records() for row in record.rows]
    for i in range(6):
        assert (f"CREDOR {i}", f"{i}.000,00") in rows, f"o credor {i} numa fileira dele"
    assert ("MATERIA PRIMA",) in rows, "a célula mesclada fica numa fileira sozinha"


def test_a_table_without_a_merged_cell_keeps_its_rows():
    rows = [row for record in _merged_cell_table(cell=False).records() for row in record.rows]
    assert rows == [(f"CREDOR {i}", f"{i}.000,00") for i in range(6)]


def test_a_tall_vertical_line_in_the_margin_does_not_join_the_text_rows():
    """A tarja vertical cobre a página inteira; as linhas do texto continuam uma por fileira."""
    lines = [("Documento assinado digitalmente", (0.95, 0.10, 0.96, 0.90))]
    lines += [
        (f"linha {i} do texto", (0.10, 0.12 + i * 0.03, 0.80, 0.135 + i * 0.03)) for i in range(5)
    ]
    result = process(make_scanned_pdf(), policy="all_cheap", cheap=[_Boxes(lines)])
    rows = [row for record in result.records() for row in record.rows]
    assert [r for r in rows if r[0].startswith("linha")] == [
        (f"linha {i} do texto",) for i in range(5)
    ]
