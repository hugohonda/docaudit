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


def _body(chunks: Sequence[docaudit.Chunk]) -> list[docaudit.Chunk]:
    """As linhas do corpo que saíram com o texto exato, na ordem do corpo.

    O reconhecedor erra uma letra ou outra conforme a fonte da máquina: o
    teste pede quase todas as linhas, e confere o giro e a caixa das que vieram.
    """
    found = _by_text(chunks)
    lines = [found[_key(line)] for line in BODY if _key(line) in found]
    assert len(lines) >= len(BODY) - 2, sorted(found)
    return lines


def _vertical(chunks: Sequence[docaudit.Chunk]) -> list[docaudit.Chunk]:
    """As linhas mais altas que largas na imagem: os pedaços da tarja da margem."""
    return [c for c in chunks if c.bbox.y1 - c.bbox.y0 > c.bbox.x1 - c.bbox.x0]


@pytest.mark.parametrize("stamp", [False, True])
@pytest.mark.parametrize("footer", [False, True])
def test_a_sheet_scanned_upside_down_is_read_line_by_line_and_the_stamps_stay(
    stamp: bool, footer: bool
) -> None:
    """O corpo sai com `turn=180` e a caixa sobre a tinta; a tarja e o rodapé seguem em pé."""
    result = docaudit.process(_sheet(180, stamp=stamp, footer=footer), cheap=[PPOCR()])
    chunks = _by_text(result.chunks)
    body = _body(result.chunks)

    assert all(c.turn == 180 for c in body)
    # Na imagem, a primeira linha lida é a mais baixa, e a leitura sobe.
    tops = [c.bbox.y0 for c in body]
    assert tops == sorted(tops, reverse=True)
    assert tops[0] > 0.5
    order = [c.reading_order or 0 for c in body]
    assert order == sorted(order)
    if footer:
        assert chunks[_key(FOOTER)].turn == 0
        assert chunks[_key(FOOTER)].bbox.y0 > 0.9
    if stamp:
        strip = _vertical(result.chunks)
        assert strip, sorted(chunks)
        assert all(c.turn == 0 for c in strip), "a tarja é do PDF, e segue em pé"
    assert "unread_lines" not in result.review().get(0, ())


@pytest.mark.parametrize("stamp", [False, True])
@pytest.mark.parametrize("footer", [False, True])
def test_an_upright_sheet_keeps_every_line_upright(stamp: bool, footer: bool) -> None:
    result = docaudit.process(_sheet(0, stamp=stamp, footer=footer), cheap=[PPOCR()])
    assert all(c.turn == 0 for c in result.chunks), sorted(_by_text(result.chunks))
    assert _body(result.chunks)


def test_a_sparse_sheet_upside_down_with_a_margin_stamp_is_read() -> None:
    """A tarja em pedaços é a maioria das linhas, e não decide: só as linhas deitadas votam."""
    pdf = _sheet(180, body=["Valor total da habilitação 1.249,01"], stamp=True)
    result = docaudit.process(pdf, cheap=[PPOCR()])
    body = [c for c in result.chunks if c not in _vertical(result.chunks)]
    text = " ".join(c.text for c in body)

    assert "1.249,01" in text, sorted(_by_text(result.chunks))
    assert "Valor total" in text, sorted(_by_text(result.chunks))
    assert all(c.turn == 180 for c in body if c.text.strip() and len(c.text.strip()) > 3)
    assert all(c.turn == 0 for c in _vertical(result.chunks)), "a página não foi lida de lado"


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
    """O que o detector acha e o reconhecedor não lê sai como caixa, e chega à página."""
    from docaudit.pdf import PageView, load_pages, opened
    from docaudit.types import Read

    pdf = _sheet(0, stamp=True)
    with opened(pdf) as doc:
        read = PPOCR().read(PageView(doc, load_pages(pdf)[0]))
    assert isinstance(read, Read)
    assert len(read.unread) < len(read), "a página foi lida: o que sobra é minoria"
    assert all(not any(c.bbox == box for c in read) for box in read.unread)
    result = docaudit.process(pdf, cheap=[PPOCR()])
    assert result.pages[0].unread_lines == read.unread
    assert result.review() == {}, "a minoria sem leitura não marca a página"
