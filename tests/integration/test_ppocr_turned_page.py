"""Uma página digitalizada de lado ou de cabeça para baixo é lida em pé, com as caixas na imagem.

Marcado `slow`: usa o PP-OCR de verdade.
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO

import pytest
from tests.support.fixtures import _font

import docaudit

pytestmark = [pytest.mark.slow, pytest.mark.integration]
pytest.importorskip("rapidocr", reason="precisa do extra `ppocr`")

from docaudit.backends.ppocr import PPOCR  # noqa: E402

ROWS = [
    ("Alfa Beta Ltda", "12.345,67"),
    ("Gama Delta", "8.901,23"),
    ("Epsilon", "4.567,89"),
]
STAMP = "Este documento foi assinado digitalmente fls. 1234"
BODY = [
    "Vistos. Trata-se de pedido de habilitação de crédito formulado",
    "pela credora em face da massa falida, no valor de R$ 12.345,67,",
    "decorrente de contrato de prestação de serviços firmado entre as",
    "partes. O administrador judicial manifestou-se pela procedência",
    "parcial do pedido, e o Ministério Público não se opôs à inclusão.",
    "É o relatório. Decido. A documentação juntada comprova a origem",
    "e o valor do crédito, que não foi impugnado pela falida no prazo.",
    "Ante o exposto, julgo procedente o pedido para determinar a",
    "inclusão do crédito no quadro geral de credores, na classe dos",
    "quirografários, com correção até a data da decretação da quebra.",
    "Intimem-se. Cumpra-se. São Paulo, 12 de março de 2019.",
    "Juíza de Direito",
]
FOOTER = "Documento assinado digitalmente, protocolo 0001234-56.2019"


def _paste_stamp(img, font, dpi: int) -> None:
    """Cola na margem direita a tarja escrita de baixo para cima, no sistema da imagem."""
    from PIL import Image, ImageDraw

    band = Image.new("L", (int(dpi * 4.5), int(dpi * 0.3)), 255)
    ImageDraw.Draw(band).text((5, 5), STAMP, fill=20, font=font)
    img.paste(band.rotate(90, expand=True), (int(dpi * 7.7), int(dpi * 3.0)))


def _sideways_table(
    angle: int, rows: Sequence[tuple[str, str]] = ROWS, stamp: bool = False
) -> bytes:
    """Uma tabela de duas colunas girada `angle` graus (anti-horário), num PDF só de imagem.

    Com `stamp`, a margem direita leva uma tarja escrita de baixo para cima.
    """
    from PIL import Image, ImageDraw

    dpi = 200
    font = _font(int(dpi * 0.13))
    if font is None:  # pragma: no cover
        pytest.skip("nenhuma font monoespaçada TrueType disponível")
    img = Image.new("L", (int(8.27 * dpi), int(11.69 * dpi)), 255)
    draw = ImageDraw.Draw(img)
    for i, (name, value) in enumerate(rows):
        y = int(dpi * (1.0 + 0.4 * i))
        draw.text((int(dpi * 0.8), y), name, fill=20, font=font)
        draw.text((int(dpi * 6.0), y), value, fill=20, font=font)
    if stamp:
        _paste_stamp(img, font, dpi)
    buf = BytesIO()
    img.rotate(angle, expand=True).save(buf, format="PDF", resolution=float(dpi))
    return buf.getvalue()


@pytest.mark.parametrize(("angle", "turn"), [(90, 270), (270, 90)])
def test_a_sideways_table_is_read_upright_with_boxes_on_the_image(angle: int, turn: int) -> None:
    result = docaudit.process(_sideways_table(angle), policy="all_cheap", cheap=[PPOCR()])
    chunks = {c.text.strip(): c for c in result.chunks}

    for name, value in ROWS:
        assert name in chunks, sorted(chunks)
        assert value in chunks, sorted(chunks)
        a, b = chunks[name], chunks[value]
        assert a.turn == turn
        assert b.turn == turn
        # On the sideways image a table row is a vertical band: name and value share its x range.
        assert min(a.bbox.x1, b.bbox.x1) > max(a.bbox.x0, b.bbox.x0)
    order = [chunks[name].reading_order or 0 for name, _ in ROWS]
    assert order == sorted(order)


def test_an_upright_page_is_not_turned() -> None:
    result = docaudit.process(_sideways_table(0), policy="all_cheap", cheap=[PPOCR()])
    assert result.chunks
    assert all(c.turn == 0 for c in result.chunks)


def test_a_sparse_upright_page_with_a_margin_stamp_stays_upright() -> None:
    """A tarja em pedaços faz maioria alta numa página de uma linha; girada, o corpo é que parte."""
    pdf = _sideways_table(0, rows=[("Valor total 1.249,01", "")], stamp=True)
    result = docaudit.process(pdf, policy="all_cheap", cheap=[PPOCR()])
    texts = [c.text.strip() for c in result.chunks]

    assert all(c.turn == 0 for c in result.chunks), texts
    assert "Valor total 1.249,01" in texts, texts


def _sheet(
    turn: int, body: Sequence[str] = BODY, stamp: bool = False, footer: bool = False
) -> bytes:
    """Uma folha de prosa digitalizada girada `turn` graus, num PDF só de imagem.

    A tarja da margem direita e o rodapé são carimbos apostos depois da
    digitalização: ficam no sistema do PDF, a tarja escrita de baixo para
    cima e o rodapé em pé, qualquer que seja o giro do papel.
    """
    from PIL import Image, ImageDraw

    dpi = 200
    font = _font(int(dpi * 0.13))
    small = _font(int(dpi * 0.1))
    if font is None or small is None:  # pragma: no cover
        pytest.skip("nenhuma font monoespaçada TrueType disponível")
    img = Image.new("L", (int(8.27 * dpi), int(11.69 * dpi)), 255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(body):
        draw.text((int(dpi * 0.8), int(dpi * (1.2 + 0.32 * i))), line, fill=20, font=font)
    img = img.rotate(turn, expand=True)
    if stamp:
        _paste_stamp(img, font, dpi)
    if footer:
        ImageDraw.Draw(img).text((int(dpi * 0.8), int(dpi * 11.1)), FOOTER, fill=20, font=small)
    buf = BytesIO()
    img.save(buf, format="PDF", resolution=float(dpi))
    return buf.getvalue()


def _by_text(chunks: Sequence[docaudit.Chunk]) -> dict[str, docaudit.Chunk]:
    """As linhas pelo texto sem espaços: o reconhecedor às vezes abre um depois da vírgula."""
    return {_key(c.text): c for c in chunks}


def _key(text: str) -> str:
    return "".join(text.split())


STAMP_WORDS = ["Este", "documento", "assinado", "digitalmente", "234"]
"""Os pedaços em que o detector parte a tarja vertical desta página."""


@pytest.mark.parametrize("stamp", [False, True])
@pytest.mark.parametrize("footer", [False, True])
def test_a_sheet_scanned_upside_down_is_read_line_by_line_and_the_stamps_stay(
    stamp: bool, footer: bool
) -> None:
    """O corpo sai com `turn=180` e a caixa sobre a tinta; a tarja e o rodapé seguem em pé."""
    result = docaudit.process(_sheet(180, stamp=stamp, footer=footer), cheap=[PPOCR()])
    chunks = _by_text(result.chunks)

    for line in BODY:
        assert _key(line) in chunks, sorted(chunks)
        assert chunks[_key(line)].turn == 180
    # Na imagem, a primeira linha lida é a mais baixa, e a leitura sobe.
    tops = [chunks[_key(line)].bbox.y0 for line in BODY]
    assert tops == sorted(tops, reverse=True)
    assert tops[0] > 0.5
    order = [chunks[_key(line)].reading_order or 0 for line in BODY]
    assert order == sorted(order)
    if footer:
        assert chunks[_key(FOOTER)].turn == 0
        assert chunks[_key(FOOTER)].bbox.y0 > 0.9
    if stamp:
        for word in STAMP_WORDS:
            assert chunks[word].turn == 0, sorted(chunks)
    assert "unread_lines" not in result.review().get(0, ())


@pytest.mark.parametrize("stamp", [False, True])
@pytest.mark.parametrize("footer", [False, True])
def test_an_upright_sheet_keeps_every_line_upright(stamp: bool, footer: bool) -> None:
    result = docaudit.process(_sheet(0, stamp=stamp, footer=footer), cheap=[PPOCR()])
    texts = _by_text(result.chunks)

    assert all(c.turn == 0 for c in result.chunks), sorted(texts)
    for line in BODY:
        assert _key(line) in texts, sorted(texts)


def test_a_sparse_sheet_upside_down_with_a_margin_stamp_is_read() -> None:
    """A tarja em pedaços é a maioria das linhas, e não decide: só as linhas deitadas votam."""
    pdf = _sheet(180, body=["Valor total da habilitação 1.249,01"], stamp=True)
    result = docaudit.process(pdf, cheap=[PPOCR()])
    chunks = _by_text(result.chunks)

    assert _key("Valor total da habilitação 1.249,01") in chunks, sorted(chunks)
    assert chunks[_key("Valor total da habilitação 1.249,01")].turn == 180


def test_a_cover_sheet_with_more_upright_stamps_than_body_keeps_the_stamps() -> None:
    """Três carimbos em pé e uma linha de corpo invertida: a maioria é em pé, e nada se perde."""
    from PIL import Image, ImageDraw

    dpi = 200
    font = _font(int(dpi * 0.13))
    if font is None:  # pragma: no cover
        pytest.skip("nenhuma font monoespaçada TrueType disponível")
    img = Image.new("L", (int(8.27 * dpi), int(11.69 * dpi)), 255)
    ImageDraw.Draw(img).text((int(dpi * 0.8), int(dpi * 1.2)), BODY[0], fill=20, font=font)
    img = img.rotate(180)
    draw = ImageDraw.Draw(img)
    stamps = [
        FOOTER,
        "Protocolado em 12 de março de 2019 às 14 horas",
        "Juntada aos autos da folha",
    ]
    for i, text in enumerate(stamps):
        draw.text((int(dpi * 0.8), int(dpi * (1.0 + 0.4 * i))), text, fill=20, font=font)
    buf = BytesIO()
    img.save(buf, format="PDF", resolution=float(dpi))
    result = docaudit.process(buf.getvalue(), cheap=[PPOCR()])
    texts = _by_text(result.chunks)

    for text in stamps:
        assert _key(text) in texts, sorted(texts)
    assert all(c.turn == 0 for c in result.chunks)


@pytest.mark.parametrize(("angle", "turn"), [(90, 270), (270, 90)])
def test_a_sideways_table_with_a_margin_stamp_is_still_read_upright(angle: int, turn: int) -> None:
    result = docaudit.process(_sideways_table(angle, stamp=True), cheap=[PPOCR()])
    chunks = {c.text.strip(): c for c in result.chunks}

    for name, value in ROWS:
        assert name in chunks, sorted(chunks)
        assert value in chunks, sorted(chunks)
        assert chunks[name].turn == turn


def test_the_lines_the_reader_detects_and_cannot_read_come_out_as_unread_boxes() -> None:
    """A tarja deixa pedaços que o detector acha e o reconhecedor não lê: caixas, sem texto."""
    from docaudit.pdf import PageView, load_pages, opened
    from docaudit.types import Read

    pdf = _sheet(0, stamp=True)
    with opened(pdf) as doc:
        read = PPOCR().read(PageView(doc, load_pages(pdf)[0]))
    assert isinstance(read, Read)
    assert read.unread
    assert len(read.unread) < len(read)
    result = docaudit.process(pdf, cheap=[PPOCR()])
    assert result.pages[0].unread_lines == read.unread
    assert result.review() == {}, "a minoria sem leitura não marca a página"
