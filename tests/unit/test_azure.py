"""O leitor `azure-read` sem rede: o pedido, a espera da operação, as caixas, o giro e as falhas."""

import io
import json
import urllib.error
import urllib.request
from email.message import Message

import pytest
from tests.support import ReaderContract
from tests.support.fixtures import EMPTY_PAGE, TEXT_CENTRAL, make_pdf, make_scanned_pdf

import docaudit
from docaudit.backends.azure import AzureRead
from docaudit.pdf import PageView, load_pages, opened
from docaudit.types import BBox, ExternalBackendError

ENDPOINT = "https://recurso.cognitiveservices.azure.com"
OPERATION = f"{ENDPOINT}/documentintelligence/documentModels/prebuilt-read/analyzeResults/1"


class _Response(io.BytesIO):
    """Uma resposta do serviço: o corpo e os cabeçalhos."""

    def __init__(self, body: object = None, **headers: str) -> None:
        super().__init__(b"" if body is None else json.dumps(body).encode())
        self.headers = Message()
        for name, value in headers.items():
            self.headers[name.replace("_", "-")] = value


def _refusal(code: int, **headers: str) -> urllib.error.HTTPError:
    message = Message()
    for name, value in headers.items():
        message[name.replace("_", "-")] = value
    body = io.BytesIO(json.dumps({"error": {"code": str(code), "message": "recusado"}}).encode())
    return urllib.error.HTTPError(ENDPOINT, code, "recusado", message, body)


def _service(monkeypatch, *answers: object) -> list[urllib.request.Request]:
    """Troca a rede e o relógio: cada pedido consome a resposta seguinte; devolve os pedidos."""
    requests: list[urllib.request.Request] = []
    queue = iter(answers)

    def urlopen(request, timeout):
        requests.append(request)
        answer = next(queue)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr("docaudit.backends.azure.time.sleep", lambda seconds: None)
    return requests


def _sent(request: urllib.request.Request) -> bytes:
    """O corpo do pedido: a imagem como ela saiu."""
    assert isinstance(request.data, bytes)
    return request.data


def _accepted() -> _Response:
    return _Response(Operation_Location=OPERATION)


def _line(text: str, polygon: list[float], offset: int) -> dict[str, object]:
    return {"content": text, "polygon": polygon, "spans": [{"offset": offset, "length": len(text)}]}


def _word(text: str, confidence: float, offset: int) -> dict[str, object]:
    return {
        "content": text,
        "polygon": [0, 0, 1, 0, 1, 1, 0, 1],
        "confidence": confidence,
        "span": {"offset": offset, "length": len(text)},
    }


def _done(lines: list[dict[str, object]], *, size=(1240, 1754), angle=0.0, words=()) -> _Response:
    page = {
        "pageNumber": 1,
        "angle": angle,
        "width": size[0],
        "height": size[1],
        "unit": "pixel",
        "words": list(words),
        "lines": lines,
    }
    return _Response({"status": "succeeded", "analyzeResult": {"pages": [page]}})


def _reader(**kwargs) -> AzureRead:
    return AzureRead(ENDPOINT, "chave", **kwargs)


def _read(reader: AzureRead, pdf: bytes | None = None):
    doc = pdf or make_scanned_pdf(pixels=(1240, 1754))
    with opened(doc) as handle:
        return list(reader.read(PageView(handle, load_pages(doc)[0], dpi=150)))


def test_a_page_becomes_one_chunk_per_line_with_the_box_on_the_image(monkeypatch):
    """A caixa é a envoltória do polígono, e a confiança é a da palavra mais duvidosa da linha."""
    lines = [
        _line("Vistos em correição", [124, 175, 620, 176, 620, 210, 124, 209], 0),
        _line("fls. 12", [124, 350, 248, 350, 248, 385, 124, 385], 20),
    ]
    words = [_word("Vistos", 0.99, 0), _word("em", 0.61, 7), _word("correição", 0.97, 10)]
    reader = _reader(price_per_page=0.0015)
    requests = _service(
        monkeypatch, _accepted(), _Response({"status": "running"}), _done(lines, words=words)
    )

    first, second = _read(reader)

    assert (first.text, second.text) == ("Vistos em correição", "fls. 12")
    assert (first.bbox.x0, first.bbox.y0, first.bbox.x1, first.bbox.y1) == pytest.approx(
        (124 / 1240, 175 / 1754, 620 / 1240, 210 / 1754)
    )
    assert first.confidence == pytest.approx(0.61)
    assert second.confidence is None, "sem palavra com confiança, a linha não inventa uma"
    assert (first.reading_order, second.reading_order) == (0, 1)
    assert (first.turn, first.source) == (0, "azure-read")
    assert reader.usage == {"calls": 1.0, "usd": pytest.approx(0.0015)}
    post, poll, _ = requests
    assert post.full_url == (
        f"{ENDPOINT}/documentintelligence/documentModels/prebuilt-read:analyze"
        "?api-version=2024-11-30"
    )
    assert post.get_header("Ocp-apim-subscription-key") == "chave"
    assert post.get_header("Content-type") == "image/png"
    assert _sent(post).startswith(b"\x89PNG")
    assert poll.full_url == OPERATION
    assert poll.get_header("Ocp-apim-subscription-key") == "chave"


def test_a_sheet_upside_down_gives_each_line_the_turn_it_is_read_in(monkeypatch):
    """O corpo invertido sai com 180 e a caixa onde a tinta está; o carimbo em pé, com 0.

    A tarja vertical é de través na página, e fica com o giro da página.
    """
    lines = [
        _line("tarja da margem", [1249, 2090, 1248, 624, 1267, 624, 1268, 2090], 0),
        _line("carimbo em pé", [483, 1646, 879, 1640, 879, 1662, 483, 1668], 16),
        _line("primeira linha do corpo", [866, 1503, 679, 1516, 677, 1481, 865, 1469], 30),
        _line("segunda linha do corpo", [850, 1348, 643, 1347, 643, 1333, 850, 1334], 54),
    ]
    _service(monkeypatch, _accepted(), _done(lines, size=(1275, 2100), angle=-179.63))

    chunks = {c.text: c for c in _read(_reader(), make_scanned_pdf(pixels=(1275, 2100)))}

    assert chunks["primeira linha do corpo"].turn == 180
    assert chunks["segunda linha do corpo"].turn == 180
    assert chunks["carimbo em pé"].turn == 0
    assert chunks["tarja da margem"].turn == 180
    body = chunks["primeira linha do corpo"]
    assert body.bbox.y0 == pytest.approx(1469 / 2100), "a caixa segue no sistema da imagem"
    assert body.as_read().y0 < chunks["segunda linha do corpo"].as_read().y0, "lida, ela vem antes"
    strip = chunks["tarja da margem"].as_read()
    assert strip.y1 - strip.y0 > strip.x1 - strip.x0, "a tarja segue vertical na página lida"


@pytest.mark.parametrize(
    ("angle", "polygon", "turn"),
    [
        (89.78, [1200, 57, 1201, 282, 1177, 283, 1176, 57], 90),
        (-90.2, [30, 1200, 29, 975, 53, 974, 54, 1200], 270),
        (-0.136, [124, 175, 620, 176, 620, 210, 124, 209], 0),
        (4.2, [124, 175, 620, 211, 618, 245, 122, 209], 0),
    ],
)
def test_the_turn_follows_the_direction_the_line_is_read_in(monkeypatch, angle, polygon, turn):
    """O serviço mede o ângulo no sentido horário; a folha torta em poucos graus não gira."""
    _service(monkeypatch, _accepted(), _done([_line("uma linha", polygon, 0)], angle=angle))

    (chunk,) = _read(_reader())

    assert chunk.turn == turn


def test_a_crop_smaller_than_the_service_accepts_goes_on_a_white_ground(monkeypatch):
    """O recorte de uma linha é mais baixo que o mínimo: vai sobre um fundo, e a caixa é dele."""
    from PIL import Image

    doc = make_scanned_pdf(pixels=(1240, 1754))
    with opened(doc) as handle:
        view = PageView(handle, load_pages(doc)[0], dpi=150)
        crop = view.region(BBox(x0=0.1, y0=0.1, x1=0.9, y1=0.115))
        width, height = crop.pixels().size
        line = _line("R$ 10,00", [10, 5, 110, 5, 110, 25, 10, 25], 0)
        requests = _service(monkeypatch, _accepted(), _done([line], size=(width, 50)))
        (chunk,) = _reader().read(crop)

    assert height < 50
    with Image.open(io.BytesIO(_sent(requests[0]))) as sent:
        assert sent.size == (width, 50)
    assert chunk.bbox.y1 == pytest.approx(min(25 / height, 1.0))
    assert chunk.bbox.x1 == pytest.approx(110 / width)


def test_a_blank_page_is_not_sent(monkeypatch):
    requests = _service(monkeypatch)

    assert _read(_reader(), make_pdf(EMPTY_PAGE)) == []
    assert requests == []


def test_an_operation_that_fails_is_a_failure_of_the_page(monkeypatch):
    failed = _Response({"status": "failed", "error": {"code": "InvalidImage", "message": "ruim"}})
    _service(monkeypatch, _accepted(), failed)

    with pytest.raises(RuntimeError, match="InvalidImage: ruim"):
        _read(_reader())


def test_a_refused_key_stops_the_document(monkeypatch):
    """A credencial recusada não é desta página: falharia em todas."""
    _service(monkeypatch, _refusal(401))

    with pytest.raises(PermissionError, match="401"):
        _read(_reader())


def test_a_busy_service_is_asked_again_after_the_wait_it_names(monkeypatch):
    waits: list[float] = []
    requests = _service(
        monkeypatch,
        _refusal(429, Retry_After="7"),
        _accepted(),
        _refusal(503),
        _done([_line("uma linha", [124, 175, 620, 176, 620, 210, 124, 209], 0)]),
    )
    monkeypatch.setattr("docaudit.backends.azure.time.sleep", waits.append)

    (chunk,) = _read(_reader(retries=2))

    assert chunk.text == "uma linha"
    assert len(requests) == 4
    assert waits[0] == 7.0, "a espera que o serviço pediu"


def test_a_service_that_stays_busy_fails_the_page(monkeypatch):
    _service(monkeypatch, _refusal(429), _refusal(429))

    with pytest.raises(RuntimeError, match="429"):
        _read(_reader(retries=1))


def test_an_operation_that_never_ends_fails_the_page(monkeypatch):
    running = [_Response({"status": "running"}) for _ in range(3)]
    _service(monkeypatch, _accepted(), *running)
    clock = iter([0.0, 1.0, 50.0, 200.0])
    monkeypatch.setattr("docaudit.backends.azure.time.monotonic", lambda: next(clock))

    with pytest.raises(RuntimeError, match="não terminou"):
        _read(_reader(timeout=120.0))


def test_the_reader_is_external_and_process_refuses_it_without_consent(monkeypatch):
    requests = _service(monkeypatch)

    with pytest.raises(ExternalBackendError):
        docaudit.process(make_scanned_pdf(), policy="all_strong", strong=_reader())
    assert requests == [], "nada sai da máquina antes da autorização"


def test_the_model_and_the_api_version_are_in_the_output_version():
    assert _reader().output_version == "1:prebuilt-read:2024-11-30"
    assert _reader(api_version="2025-01-01").output_version != _reader().output_version
    with pytest.raises(ValueError, match="obrigatórios"):
        AzureRead("", "chave")
    with pytest.raises(ValueError, match="negativo"):
        _reader(retries=-1)


def test_as_the_strong_reader_it_reads_the_page_the_cheap_read_left_empty(monkeypatch):
    """De ponta a ponta: a página vazia escala, sai com a autorização, e o gasto conta."""
    lines = [_line("Termo de audiência", [124, 175, 620, 176, 620, 210, 124, 209], 0)]
    _service(monkeypatch, _accepted(), _done(lines))

    result = docaudit.process(
        make_scanned_pdf(pixels=(1240, 1754)),
        policy="evidence",
        cheap=["text_layer"],
        strong=_reader(price_per_page=0.0015),
        allow_external=True,
    )

    assert [c.text for c in result.chunks] == ["Termo de audiência"]
    assert result.read_by() == {0: ("azure-read",)}
    assert (result.spent.calls, result.spent.usd) == (1.0, pytest.approx(0.0015))


class TestAzureReadContract(ReaderContract):
    @pytest.fixture
    def reader(self, monkeypatch):
        """Um serviço que responde sempre a mesma linha, quantas vezes for chamado."""

        def urlopen(request, timeout):
            if request.data is not None:
                return _accepted()
            return _done(
                [_line("uma linha", [60, 60, 300, 60, 300, 90, 60, 90], 0)], size=(900, 1200)
            )

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        monkeypatch.setattr("docaudit.backends.azure.time.sleep", lambda seconds: None)
        return _reader()


def test_the_page_with_text_is_sent_as_pixels_and_not_as_its_text_layer(monkeypatch):
    """A página nato-digital também vai em PNG: o serviço lê o que a biblioteca renderizou."""
    requests = _service(
        monkeypatch, _accepted(), _done([_line("uma linha", [60, 60, 300, 60, 300, 90, 60, 90], 0)])
    )

    _read(_reader(), make_pdf(TEXT_CENTRAL))

    assert _sent(requests[0]).startswith(b"\x89PNG")


def test_the_amount_the_service_reads_with_rs_for_the_currency_sign_still_counts(monkeypatch):
    """O serviço lê `R$` como `RS`. O leitor devolve o que veio, e a regra do campo o aceita."""
    from docaudit.types import Chunk

    class _Misread:
        name = "cheap"
        external = False
        output_version = "1"

        def read(self, view):
            view.image()
            box = BBox(x0=0.1, y0=0.1, x1=0.5, y1=0.12)
            return [Chunk.make(view.page, box, self.name, "Total R$ 1.234.56", reading_order=0)]

    lines = [_line("Total RS 1.234,56", [124, 175, 620, 176, 620, 210, 124, 209], 0)]
    _service(monkeypatch, _accepted(), _done(lines))

    result = docaudit.process(
        make_scanned_pdf(pixels=(1240, 1754)),
        policy="evidence",
        cheap=[_Misread()],
        strong=_reader(),
        allow_external=True,
    )

    assert [c.text for c in result.chunks] == ["Total RS 1.234,56"]
    (amount,) = result.entities
    assert (amount.value, amount.state.value) == ("RS 1.234,56", "well_formed")


def test_the_result_of_a_whole_page_is_handed_over_and_gives_the_same_lines_later(monkeypatch):
    """Quem guarda o resultado do serviço monta as mesmas linhas depois, sem pagar de novo."""
    kept: list[tuple[PageView, dict[str, object]]] = []
    reader = _reader(on_result=lambda view, result: kept.append((view, dict(result))))
    lines = [_line("Vistos em correição", [124, 175, 620, 176, 620, 210, 124, 209], 0)]
    words = [_word("Vistos", 0.99, 0), _word("em", 0.61, 7), _word("correição", 0.97, 10)]
    _service(monkeypatch, _accepted(), _done(lines, words=words))
    doc = make_scanned_pdf(pixels=(1240, 1754))

    with opened(doc) as handle:
        view = PageView(handle, load_pages(doc)[0], dpi=150)
        read = list(reader.read(view))
        ((seen, result),) = kept
        again = reader.lines_of(view, json.loads(json.dumps(result)))

    assert seen is view
    assert again == read
    assert reader.usage == {"calls": 1.0}, "montar as linhas de um resultado guardado não conta"


def test_the_result_of_a_crop_is_not_handed_over(monkeypatch):
    """O resultado de um recorte não é o da página, e não serve a quem a guarda."""
    kept: list[object] = []
    reader = _reader(on_result=lambda view, result: kept.append(result))
    line = _line("R$ 10,00", [10, 5, 110, 5, 110, 25, 10, 25], 0)
    doc = make_scanned_pdf(pixels=(1240, 1754))

    with opened(doc) as handle:
        crop = PageView(handle, load_pages(doc)[0], dpi=150).region(
            BBox(x0=0.1, y0=0.1, x1=0.9, y1=0.3)
        )
        _service(monkeypatch, _accepted(), _done([line], size=crop.pixels().size))
        (chunk,) = reader.read(crop)

    assert chunk.text == "R$ 10,00"
    assert kept == []


def test_a_result_kept_from_a_turned_page_gives_the_lines_of_the_page_as_it_is(monkeypatch):
    """A página foi enviada em meia-volta; guardado, o resultado serve à página como ela é."""
    kept: list[dict[str, object]] = []
    reader = _reader(on_result=lambda view, result: kept.append(dict(result)))
    lines = [_line("corpo lido em pé", [124, 175, 620, 176, 620, 210, 124, 209], 0)]
    _service(monkeypatch, _accepted(), _done(lines))
    doc = make_scanned_pdf(pixels=(1240, 1754))

    with opened(doc) as handle:
        view = PageView(handle, load_pages(doc)[0], dpi=150)
        turned = view.region(BBox(x0=0.0, y0=0.0, x1=1.0, y1=1.0), turn=180)
        (sent,) = reader.read(turned)
        (as_it_is,) = reader.lines_of(view, kept[0], turn=180)
        (same,) = reader.lines_of(turned, kept[0], turn=180)

    on_the_page = turned.to_page(sent.bbox)
    assert same == sent
    assert as_it_is.turn == 180
    assert (as_it_is.bbox.x0, as_it_is.bbox.y0, as_it_is.bbox.x1, as_it_is.bbox.y1) == (
        pytest.approx((on_the_page.x0, on_the_page.y0, on_the_page.x1, on_the_page.y1))
    )
