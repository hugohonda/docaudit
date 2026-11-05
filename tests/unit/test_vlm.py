"""O leitor `vlm` sem servidor: página inteira, por região, versão de saída e o portão externo."""

import io
import json
from email.message import Message

import pytest
from tests.support.fixtures import EMPTY_PAGE, make_pdf, make_scanned_pdf

import docaudit
from docaudit.backends.layout import PPDocLayout, Region
from docaudit.backends.vlm import VLM
from docaudit.types import BBox, ExternalBackendError


def _stubbed(monkeypatch, answers: dict[str, str], **kwargs) -> VLM:
    """`answers` mapeia prompt → texto devolvido; o servidor nunca é chamado."""
    reader = VLM(**kwargs)
    monkeypatch.setattr(reader, "_ask", lambda image, prompt: answers[prompt])
    monkeypatch.setattr(reader, "_served_model", lambda: "stub.gguf")
    return reader


def test_without_layout_the_page_is_one_chunk_covering_the_sheet(monkeypatch):
    reader = _stubbed(monkeypatch, {"Text Recognition:": "EDITAL\n\n  Termo de Audiência nº 3  \n"})
    result = docaudit.process(make_scanned_pdf(), policy="all_strong", cheap=[], strong=reader)
    (chunk,) = result.chunks
    assert chunk.text == "EDITAL\nTermo de Audiência nº 3"
    assert chunk.bbox.area == 1.0
    assert chunk.source == "vlm"
    assert chunk.kind is None, "sem detector, nada classifica"
    assert result.refs() == {"p0:0": chunk}, "uma referência para a folha"


def test_degenerate_lines_in_another_script_are_dropped(monkeypatch):
    """Numa página sem texto o modelo repete uma frase em outro alfabeto."""
    reader = _stubbed(
        monkeypatch, {"Text Recognition:": "歩道は歩道の上にある歩道です。\nfls. 12\n歩道の下には"}
    )
    result = docaudit.process(make_scanned_pdf(), policy="all_strong", cheap=[], strong=reader)
    assert [c.text for c in result.chunks] == ["fls. 12"]
    only_noise = _stubbed(monkeypatch, {"Text Recognition:": "歩道は歩道の上にある"})
    assert docaudit.process(make_scanned_pdf(), policy="all_strong", strong=only_noise).chunks == ()


@pytest.fixture
def regions():
    return [
        Region(label="text", bbox=BBox(x0=0.1, y0=0.1, x1=0.9, y1=0.3)),
        Region(label="table", bbox=BBox(x0=0.1, y0=0.4, x1=0.9, y1=0.7)),
        Region(label="text", bbox=BBox(x0=0.1, y0=0.8, x1=0.9, y1=0.9)),
    ]


@pytest.mark.parametrize("concurrency", [1, 3])
def test_with_layout_each_region_is_a_chunk_with_its_box_and_prompt(
    monkeypatch, regions, concurrency
):
    """A tabela recebe o prompt de tabela; duas regiões com o mesmo texto têm ids distintos."""
    layout = PPDocLayout()
    monkeypatch.setattr(layout, "detect", lambda image: regions)
    reader = _stubbed(
        monkeypatch,
        {"Text Recognition:": "R$ 0,00", "Table Recognition:": "| nome | valor |\n| A | 1 |"},
        layout=layout,
        concurrency=concurrency,
    )
    result = docaudit.process(make_scanned_pdf(), policy="all_strong", cheap=[], strong=reader)
    assert [c.text for c in result.chunks] == [
        "R$ 0,00",
        "| nome | valor |\n| A | 1 |",
        "R$ 0,00",
    ]
    assert [c.bbox for c in result.chunks] == [r.bbox for r in regions]
    assert [c.reading_order for c in result.chunks] == [0, 1, 2]
    assert len({c.id for c in result.chunks}) == 3
    assert [c.kind for c in result.chunks] == ["text", "table", "text"], "o tipo da região"


def test_table_markup_becomes_rows_of_cells(monkeypatch, regions):
    """Nome e valor da mesma linha da tabela ficam na mesma linha de texto."""
    layout = PPDocLayout()
    monkeypatch.setattr(layout, "detect", lambda image: regions[1:2])
    html = "<table><tr><td>nome</td><th>valor</th></tr>\n<tr><td>A</td><td>1</td></tr></table>"
    reader = _stubbed(monkeypatch, {"Table Recognition:": html}, layout=layout)
    (chunk,) = docaudit.process(make_scanned_pdf(), policy="all_strong", strong=reader).chunks
    assert chunk.text == "nome | valor |\nA | 1 |"

    otsl = "<fcel>303<fcel>José da Silva<fcel>R$ 2.462,23<nl><fcel>198<ecel><fcel>R$ 18,30<nl>"
    paddle = _stubbed(
        monkeypatch, {"Table Recognition:": otsl}, model="paddleocr-vl", layout=layout
    )
    (chunk,) = docaudit.process(make_scanned_pdf(), policy="all_strong", strong=paddle).chunks
    assert chunk.text == "| 303 | José da Silva | R$ 2.462,23\n| 198 |  | R$ 18,30"


def test_a_page_the_detector_cannot_segment_is_read_whole(monkeypatch):
    """Num escaneamento degradado o detector devolve nada, ou só uma imagem descartada."""
    layout = PPDocLayout()
    monkeypatch.setattr(layout, "detect", lambda image: [])
    reader = _stubbed(monkeypatch, {"Text Recognition:": "RELACAO DE PAGAMENTOS"}, layout=layout)
    (chunk,) = docaudit.process(make_scanned_pdf(), policy="all_strong", strong=reader).chunks
    assert chunk.text == "RELACAO DE PAGAMENTOS"
    assert chunk.bbox.area == 1.0


def test_an_empty_region_leaves_no_chunk_and_the_order_stays_dense(monkeypatch, regions):
    layout = PPDocLayout()
    monkeypatch.setattr(layout, "detect", lambda image: regions)
    reader = _stubbed(
        monkeypatch, {"Text Recognition:": "texto", "Table Recognition:": "   "}, layout=layout
    )
    result = docaudit.process(make_scanned_pdf(), policy="all_strong", cheap=[], strong=reader)
    assert [c.reading_order for c in result.chunks] == [0, 1]


def test_a_page_of_one_color_is_not_sent_to_the_model(monkeypatch):
    """O GLM-OCR responde à folha em branco com um comentário, que viraria texto."""
    reader = _stubbed(monkeypatch, {})
    monkeypatch.setattr(reader, "_ask", lambda image, prompt: pytest.fail("chamou o modelo"))
    result = docaudit.process(make_pdf(EMPTY_PAGE), policy="all_strong", cheap=[], strong=reader)
    assert not result.chunks


def test_output_version_names_the_served_model_the_preset_and_the_detector(monkeypatch):
    page = _stubbed(monkeypatch, {})
    assert page.output_version == "3:stub.gguf:glm-ocr:page"
    generic = _stubbed(monkeypatch, {}, model="generic")
    assert generic.output_version != page.output_version
    paddle = _stubbed(monkeypatch, {}, model="paddleocr-vl")
    assert paddle.output_version == "3:stub.gguf:paddleocr-vl:page"
    with_layout = _stubbed(monkeypatch, {}, layout=PPDocLayout(threshold=0.4, drop=("seal",)))
    assert with_layout.output_version.endswith(":pp_doclayoutv3:2:29193c81:0.4:seal")


def test_unknown_preset_is_refused_at_construction():
    with pytest.raises(ValueError, match="glm-ocr"):
        VLM(model="nao-existe")  # type: ignore[arg-type]


def test_a_remote_server_is_external_and_refused_by_default():
    assert not VLM("http://localhost:8089").external
    assert VLM("http://gpu.example.com:8089", served="m").external
    with pytest.raises(ValueError, match="served"):
        VLM("http://gpu.example.com:8089")
    with pytest.raises(ExternalBackendError, match="vlm"):
        docaudit.process(
            make_scanned_pdf(),
            policy="all_strong",
            strong=VLM("http://gpu.example.com:8089", served="m"),
        )


# ── Um modelo hospedado, pela mesma classe ────────────────────────────────────


def _hosted(monkeypatch, text: str = "EDITAL", usage: dict | None = None, **kwargs) -> VLM:
    """Captura o pedido e devolve uma resposta no formato da OpenAI, com `usage`."""
    reader = VLM("https://api.example.com", "generic", served="modelo-x", **kwargs)
    sent: list[dict] = []

    def post(request):
        sent.append({"headers": dict(request.header_items()), "body": json.loads(request.data)})
        response: dict = {"choices": [{"message": {"content": text}}]}
        if usage is not None:
            response["usage"] = usage
        return response

    monkeypatch.setattr(reader, "_post", post)
    reader.sent = sent  # type: ignore[attr-defined]
    return reader


def test_served_model_goes_in_the_request_with_the_credential_and_no_model_listing(monkeypatch):
    reader = _hosted(monkeypatch, api_key="s3cret")
    assert reader.output_version == "3:modelo-x:generic:page", "sem consultar /v1/models"
    assert reader.external
    result = docaudit.process(
        make_scanned_pdf(), policy="all_strong", cheap=[], strong=reader, allow_external=True
    )
    assert [c.text for c in result.chunks] == ["EDITAL"]
    (request,) = reader.sent  # type: ignore[attr-defined]
    assert request["body"]["model"] == "modelo-x"
    assert request["body"]["max_tokens"] == 4096
    assert "reasoning_effort" not in request["body"], "o padrão do servidor"
    assert request["headers"]["Authorization"] == "Bearer s3cret"
    assert "Transcreva" in request["body"]["messages"][0]["content"][1]["text"]


def test_usage_counts_tokens_and_dollars_only_for_what_was_called(monkeypatch, tmp_path):
    """A segunda execução vem do cache e não gasta nada; o contador do leitor não zera."""
    from docaudit.cache import ModelCallCache

    usage = {"prompt_tokens": 1000, "completion_tokens": 500}
    reader = _hosted(monkeypatch, usage=usage, prices=(2.0, 10.0))
    assert isinstance(reader, docaudit.Metered)
    cache = ModelCallCache(tmp_path / "c.sqlite")
    kwargs = {
        "policy": "all_strong",
        "cheap": [],
        "strong": reader,
        "allow_external": True,
        "cache": cache,
    }

    first = docaudit.process(make_scanned_pdf(), **kwargs)
    assert first.spent.calls == 1.0
    assert first.spent.tokens_in == 1000.0
    assert first.spent.tokens_out == 500.0
    assert first.spent.usd == pytest.approx(0.002 + 0.005)

    second = docaudit.process(make_scanned_pdf(), **kwargs)
    assert second.spent.pages_strong_cached == 1.0
    assert second.spent.calls == 0.0
    assert second.spent.usd == 0.0
    assert reader.usage["usd"] == pytest.approx(0.007), "o leitor acumula; o Result desconta"
    cache.close()


def test_without_prices_there_is_no_dollar_figure(monkeypatch):
    reader = _hosted(monkeypatch, usage={"prompt_tokens": 10, "completion_tokens": 1})
    result = docaudit.process(
        make_scanned_pdf(), policy="all_strong", cheap=[], strong=reader, allow_external=True
    )
    assert result.spent.tokens_in == 10.0
    assert result.spent.usd is None


def test_reasoning_goes_in_the_request_and_in_the_output_version(monkeypatch):
    reader = _hosted(monkeypatch, reasoning="none")
    assert reader.output_version == "3:modelo-x:generic:page:reasoning=none"
    reader._ask(b"png", "p")
    (request,) = reader.sent  # type: ignore[attr-defined]
    assert request["body"]["reasoning_effort"] == "none"


def test_thinking_tokens_outside_completion_tokens_count_as_output(monkeypatch):
    """O servidor compatível do Gemini deixa o pensamento só em `total_tokens`."""
    usage = {"prompt_tokens": 15, "completion_tokens": 35, "total_tokens": 302}
    reader = _hosted(monkeypatch, usage=usage, prices=(0.0, 1e6))
    reader._ask(b"png", "p")
    assert reader.usage["tokens_out"] == 287.0, "35 de resposta e 252 de pensamento"
    assert reader.usage["usd"] == 287.0


def test_a_reader_without_usage_adds_nothing_to_spent(monkeypatch):
    reader = _stubbed(monkeypatch, {"Text Recognition:": "x"})
    monkeypatch.delattr(reader, "usage")
    result = docaudit.process(make_scanned_pdf(), policy="all_strong", cheap=[], strong=reader)
    assert result.spent.calls is None


def _answering(monkeypatch, *, body: bytes = b"", raises: Exception | None = None) -> list[int]:
    """Troca a rede: cada pedido devolve `body` ou levanta `raises`; conta os pedidos."""
    import urllib.request

    calls: list[int] = []

    def urlopen(request, timeout):
        calls.append(1)
        if raises is not None:
            raise raises
        return io.BytesIO(body)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return calls


def _local() -> VLM:
    return VLM("http://127.0.0.1:8089", "generic", served="m")


def test_a_server_error_fails_the_page_without_retrying(monkeypatch):
    """Quanto esperar e quantas vezes repetir é de quem chama."""
    import urllib.error

    error = urllib.error.HTTPError("u", 429, "wait", Message(), io.BytesIO(b"slow"))
    calls = _answering(monkeypatch, raises=error)
    with pytest.raises(RuntimeError, match="429"):
        _local()._ask(b"png", "p")
    assert calls == [1]


def test_an_answer_cut_at_the_token_cap_is_a_failure_not_a_reading(monkeypatch):
    """`finish_reason` "length": o texto acabou no meio; a leitura barata fica."""
    cut = {"choices": [{"message": {"content": "texto que pa"}, "finish_reason": "length"}]}
    _answering(monkeypatch, body=json.dumps(cut).encode())
    with pytest.raises(RuntimeError, match="cortada"):
        _local()._ask(b"png", "p")


def test_a_timeout_waiting_for_the_answer_fails_the_page_not_the_document(monkeypatch):
    """O `urllib` só embrulha o envio; o tempo esgotado na resposta chega cru."""
    _answering(monkeypatch, raises=TimeoutError("timed out"))
    with pytest.warns(RuntimeWarning, match="não pôde ser lida"):
        result = docaudit.process(
            make_scanned_pdf(), policy="all_strong", cheap=["text_layer"], strong=_local()
        )
    assert result.spent.pages_strong_failed == 1.0, "o documento termina; a página conta como falha"
    assert len(result.pages) == 1


@pytest.mark.parametrize(
    ("body", "message"),
    [(b"<html>502</html>", "não pôde ser lida"), (b"[]", "não é um objeto"), (b"{}", "sem texto")],
)
def test_an_answer_that_does_not_read_is_a_failure_of_the_page(monkeypatch, body, message):
    _answering(monkeypatch, body=body)
    with pytest.raises(RuntimeError, match=message):
        _local()._ask(b"png", "p")


def test_a_refused_connection_still_stops_the_document(monkeypatch):
    import urllib.error

    _answering(monkeypatch, raises=urllib.error.URLError(ConnectionRefusedError(61, "refused")))
    with pytest.raises(ConnectionError, match="sem servidor"):
        _local()._ask(b"png", "p")


def test_usage_adds_up_when_regions_are_counted_from_several_threads():
    """Cada soma é ler, somar e gravar; sem a trava, duas threads perdem uma soma."""
    import time
    from concurrent.futures import ThreadPoolExecutor

    class SlowDict(dict):
        def __getitem__(self, key):
            value = super().__getitem__(key)
            time.sleep(0.001)  # entre ler e gravar, a vez passa a outra thread
            return value

    reader = VLM("http://127.0.0.1:8089", "generic", served="m", prices=(1.0, 1.0))
    reader.usage = SlowDict(reader.usage)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda _: reader._count({"prompt_tokens": 1, "completion_tokens": 2}), range(40)
            )
        )
    assert reader.usage["calls"] == 40.0
    assert reader.usage["tokens_in"] == 40.0
    assert reader.usage["usd"] == pytest.approx(40 * 3 / 1e6)
