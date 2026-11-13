"""Construtores de PDF e fixtures de página para a suíte.

Pillow vem com o núcleo; o import dele fica dentro dos construtores que o
usam, como no pacote.
"""

from __future__ import annotations

import zlib
from collections.abc import Sequence
from contextlib import contextmanager

import pytest

from docaudit.pdf import PageView, opened, pages_of
from docaudit.types import Page, PageDimensions, Substrate

__all__ = [
    "EMPTY_PAGE",
    "NOTICE_LINES",
    "TEXT_CENTRAL",
    "TEXT_MARGIN",
    "blank_view",
    "make_notice_pdf",
    "make_page",
    "make_pdf",
    "make_scanned_pdf",
    "scanned_view",
]

TEXT_CENTRAL = "BT /F1 24 Tf 100 400 Td (EDITAL DE CITACAO - RELACAO) Tj ET"
"""Uma linha de texto à vista no corpo da folha, sem raster: `BORN_DIGITAL`."""

TEXT_MARGIN = "BT /F1 8 Tf 20 820 Td (fls. 1 - PJe) Tj ET"
"""Só uma linha de margem, sem raster.

Todo texto à vista numa página sem raster faz dela `BORN_DIGITAL`, onde quer
que esteja: não há imagem que um OCR leia.
"""

EMPTY_PAGE = "BT ET"
"""Sem texto algum: a página é imagem pura."""


def _assemble(
    objs: Sequence[bytes],
    *,
    info: dict[str, str] | None = None,
    ids: tuple[bytes, bytes] | None = None,
    incremental: bool = False,
) -> bytes:
    """Monta corpo, tabela xref e trailer de um PDF a partir dos objetos.

    `info` vira o dicionário `/Info` do trailer, `ids` o par `/ID`, e
    `incremental` grava por cima uma atualização que troca o `/Info`: um
    segundo trailer, como um editor que salvou de novo sem reescrever o arquivo.
    """
    objs = list(objs)
    if info is not None:
        entries = "".join(f"/{k}({v})" for k, v in info.items())
        objs.append(f"<<{entries}>>".encode("latin-1"))
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj" % i + obj + b"endobj\n"
    size = len(objs) + 1
    trailer = b"/Size %d/Root 1 0 R" % size
    if info is not None:
        trailer += b"/Info %d 0 R" % len(objs)
    if ids is not None:
        trailer += b"/ID[<%s><%s>]" % (ids[0].hex().encode(), ids[1].hex().encode())
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer<<" + trailer + b">>\nstartxref\n%d\n%%%%EOF\n" % xref
    if incremental:
        # A atualização regrava o último objeto, o `/Info` quando há, com uma
        # tabela xref só para ele e um trailer que aponta para o anterior.
        updated = objs[-1] if info is None else b"<</Producer(update)>>"
        offset = len(out)
        out += b"%d 0 obj" % len(objs) + updated + b"endobj\n"
        xref2 = len(out)
        out += b"xref\n%d 1\n%010d 00000 n \n" % (len(objs), offset)
        out += b"trailer<<" + trailer + b"/Prev %d>>\nstartxref\n%d\n%%%%EOF\n" % (xref, xref2)
    return bytes(out)


def make_pdf(
    *content_streams: str,
    mediabox: str = "0 0 595 842",
    rotate: int = 0,
    to_unicode: dict[str, str] | None = None,
    info: dict[str, str] | None = None,
    ids: tuple[bytes, bytes] | None = None,
    signature: bool = False,
    incremental: bool = False,
) -> bytes:
    """Monta um PDF mínimo e válido, uma página por content stream.

    `mediabox` e `rotate` valem para todas as páginas: uma folha cuja origem
    não é (0, 0), e uma folha exibida girada. `to_unicode` dá à fonte uma
    tabela ToUnicode: cada caractere do content stream vira o texto mapeado,
    que pode ter mais de um ponto de código. `info`, `ids` e `incremental`
    são os de `_assemble`. `signature` declara uma assinatura digital num
    campo de formulário, com `/ByteRange` que cobre o arquivo inteiro: o
    pdfium a lê sem conferir, e é assim que `facts_of` a vê.
    """
    objs: list[bytes] = []
    n_pages = len(content_streams)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n_pages))
    sig_ref = 4 + 2 * n_pages + (1 if to_unicode else 0)

    acroform = f"/AcroForm<</Fields[{sig_ref} 0 R]/SigFlags 3>>" if signature else ""
    objs.append(f"<</Type/Catalog/Pages 2 0 R{acroform}>>".encode())
    objs.append(f"<</Type/Pages/Kids[{kids}]/Count {n_pages}>>".encode())
    cmap_ref = f"/ToUnicode {4 + 2 * n_pages} 0 R" if to_unicode else ""
    objs.append(f"<</Type/Font/Subtype/Type1/BaseFont/Helvetica{cmap_ref}>>".encode())
    for i, stream in enumerate(content_streams):
        body = stream.encode()
        annots = f"/Annots[{sig_ref} 0 R]" if signature and i == 0 else ""
        objs.append(
            f"<</Type/Page/Parent 2 0 R/MediaBox[{mediabox}]/Rotate {rotate}{annots}"
            f"/Contents {5 + 2 * i} 0 R/Resources<</Font<</F1 3 0 R>>>>>>".encode()
        )
        objs.append(b"<</Length %d>>stream\n" % len(body) + body + b"\nendstream")
    if to_unicode:
        pairs = "\n".join(
            f"<{ord(code):02X}> <{text.encode('utf-16-be').hex().upper()}>"
            for code, text in to_unicode.items()
        )
        cmap = (
            "/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
            "1 begincodespacerange <00> <FF> endcodespacerange\n"
            f"{len(to_unicode)} beginbfchar\n{pairs}\nendbfchar\n"
            "endcmap CMapName currentdict /CMap defineresource pop end end"
        ).encode()
        objs.append(b"<</Length %d>>stream\n" % len(cmap) + cmap + b"\nendstream")
    if signature:
        # O `/ByteRange` tem largura fixa: o tamanho do arquivo só se sabe depois de
        # montar, e a segunda montagem, com o número certo, tem o mesmo tamanho.
        def field(total: int) -> bytes:
            return (
                b"<</Type/Annot/Subtype/Widget/FT/Sig/T(Assinatura1)/F 132/Rect[0 0 0 0]"
                b"/P 4 0 R/V<</Type/Sig/Filter/Adobe.PPKLite/SubFilter/ETSI.CAdES.detached"
                b"/M(D:20240315103000-03'00')/Reason(Juntada)/ByteRange[0 0000000000 0000000000 "
                + b"%010d" % total
                + b"]/Contents<00>>>>>"
            )

        # A assinatura cobre o arquivo como estava ao assinar; a atualização
        # incremental vem depois dela e fica de fora do `/ByteRange`.
        probe = _assemble([*objs, field(0)], info=info, ids=ids)
        return _assemble([*objs, field(len(probe))], info=info, ids=ids, incremental=incremental)

    return _assemble(objs, info=info, ids=ids, incremental=incremental)


_A4 = PageDimensions(width_pt=595.0, height_pt=842.0, width_px=1654, height_px=2339, dpi=200)


def make_page(index: int = 0, *, substrate: Substrate = Substrate.IMAGE_ONLY) -> Page:
    """Uma `Page` sintética, sem hash de imagem.

    Sem hash de propósito: é o estado em que `pages_of` devolve uma página de
    verdade, enquanto nada foi renderizado.
    """
    return Page(doc_id="test", index=index, dimensions=_A4, substrate=substrate)


def make_scanned_pdf(
    text_lines: Sequence[str] = (),
    *,
    pixels: tuple[int, int] = (120, 170),
    render_mode: int = 3,
    text_before_image: bool = False,
    raster_box: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0),
    text_y: int = 700,
    text_in_form: bool = False,
    text_lines_below: Sequence[str] = (),
    text_y_below: int = 300,
    extra_raster_boxes: Sequence[tuple[float, float, float, float]] = (),
    stamped: Sequence[str] = (),
    font: str = "Helvetica",
) -> bytes:
    """PDF de uma página com raster de página inteira, e opcionalmente camada de texto.

    `pixels` é o tamanho do raster: 120 por 170 cabe num teste e dá 14 dpi
    numa folha A4; 1240 por 1754 é uma digitalização a 150 dpi.

    Sem `text_lines` o resultado é `IMAGE_ONLY`. Com elas é `SEARCHABLE_SCAN`: o
    substrato que extrai texto limpo e mesmo assim não pode ser confiado, que é
    o caso central da biblioteca e o mais fácil de classificar errado.

    O texto sai em modo invisível (`3 Tr`), que é como um motor de OCR de
    verdade o insere: desenhado sem tinta por cima da imagem, para que a página
    mantenha a aparência do original e ainda assim possa ser buscada.

    `render_mode=0` desenha o texto visível; com `text_before_image` ele vem
    antes da imagem no fluxo, e a imagem o cobre, que é a segunda forma de
    esconder uma camada. `raster_box` posiciona o raster em frações da folha,
    para montar um diário cuja digitalização ocupa só o miolo; `text_y` é a
    altura, em pontos, da primeira linha de texto.

    `text_in_form` põe o texto num formulário XObject, desenhado na origem do
    formulário e levado à altura certa pela matriz do `Do`: é como um
    gerador estampa a tarja lateral de um tribunal.

    `text_lines_below` são linhas visíveis a partir de `text_y_below`, para
    uma página com texto dos dois lados de uma figura. `extra_raster_boxes`
    desenha o mesmo raster de novo em outras posições, antes do principal no
    fluxo, para uma página com mais de uma figura. `stamped` são linhas
    visíveis desenhadas depois de tudo, no pé da folha, como a tarja que o
    tribunal põe por cima da digitalização. `font` é o nome base da fonte do
    texto: `GlyphLessFont` é a que o Tesseract deixa na camada que escreve.
    """
    w_px, h_px = pixels
    raw = bytes([200 + (i * 7) % 40 for i in range(w_px * h_px)])
    comp = zlib.compress(raw)
    fx0, fy0, fx1, fy1 = raster_box
    image_op = (
        f"q {595 * (fx1 - fx0):.2f} 0 0 {842 * (fy1 - fy0):.2f} "
        f"{595 * fx0:.2f} {842 * fy0:.2f} cm /Im0 Do Q"
    )
    for ex0, ey0, ex1, ey1 in extra_raster_boxes:
        image_op = (
            f"q {595 * (ex1 - ex0):.2f} 0 0 {842 * (ey1 - ey0):.2f} "
            f"{595 * ex0:.2f} {842 * ey0:.2f} cm /Im0 Do Q\n" + image_op
        )
    # Dentro do formulário o texto começa na origem dele, e o `cm` do `Do` o
    # leva à altura certa.
    y = 0 if text_in_form else text_y
    text_ops: list[str] = []
    for ln in text_lines:
        esc = ln.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        text_ops.append(f"BT {render_mode} Tr /F1 10 Tf 70 {y} Td ({esc}) Tj ET")
        y -= 18
    y = text_y_below
    for ln in text_lines_below:
        esc = ln.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        text_ops.append(f"BT {render_mode} Tr /F1 10 Tf 70 {y} Td ({esc}) Tj ET")
        y -= 18
    form = b""
    if text_in_form:
        form = "\n".join(text_ops).encode("latin-1", "replace")
        text_ops = [f"q 1 0 0 1 0 {text_y} cm /Fm0 Do Q"]
    content = [*text_ops, image_op] if text_before_image else [image_op, *text_ops]
    for n, ln in enumerate(stamped):
        esc = ln.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        content.append(f"BT 0 Tr /F1 6 Tf 20 {40 - 9 * n} Td ({esc}) Tj ET")
    stream = "\n".join(content).encode("latin-1", "replace")

    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[4 0 R]/Count 1>>",
        b"<</Type/Font/Subtype/Type1/BaseFont/%s>>" % font.encode(),
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 5 0 R"
        b"/Resources<</Font<</F1 3 0 R>>/XObject<</Im0 6 0 R"
        + (b"/Fm0 7 0 R" if text_in_form else b"")
        + b">>>>>>",
        b"<</Length %d>>stream\n" % len(stream) + stream + b"\nendstream",
        (
            f"<</Type/XObject/Subtype/Image/Width {w_px}/Height {h_px}"
            f"/ColorSpace/DeviceGray/BitsPerComponent 8/Filter/FlateDecode"
            f"/Length {len(comp)}>>stream\n"
        ).encode()
        + comp
        + b"\nendstream",
    ]
    if text_in_form:
        objs.append(
            b"<</Type/XObject/Subtype/Form/BBox[0 0 595 842]/Resources<</Font<</F1 3 0 R>>>>"
            b"/Length %d>>stream\n" % len(form) + form + b"\nendstream"
        )
    return _assemble(objs)


NOTICE_LINES = (
    "PODER JUDICIARIO DO ESTADO DE SAO PAULO",
    "EDITAL DE CONVOCACAO DE INTERESSADOS",
    "Processo no 1000123-47.2024.8.26.0100",
    "NOME                       CLASSE         VALOR",
    "METALURGICA ANDRADE LTDA   Classe I       R$ 1.284.350,00",
    "BANCO CREDITO NACIONAL SA  Classe II      R$ 4.750.000,00",
)
"""Um edital com uma relação de nome e valor, como sai de um auto digitalizado."""


def _font(size: int):
    from PIL import ImageFont

    for path in (
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return None


def make_notice_pdf(
    lines: Sequence[str] = NOTICE_LINES, *, dpi: int = 200, scale: float = 0.13
) -> bytes:
    """Rasteriza o edital para um PDF só de imagem, como um auto digitalizado.

    `scale` controla o corpo da fonte em fração de polegada. O padrão é
    legível; valores baixos produzem a página degradada que motiva a escalada.
    """
    from io import BytesIO

    from PIL import Image, ImageDraw

    font = _font(int(dpi * scale))
    if font is None:  # pragma: no cover
        pytest.skip("nenhuma font monoespaçada TrueType disponível")

    img = Image.new("L", (int(8.27 * dpi), int(11.69 * dpi)), 255)
    draw = ImageDraw.Draw(img)
    y = int(dpi * 0.9)
    for line in lines:
        draw.text((int(dpi * 0.8), y), line, fill=20, font=font)
        y += int(dpi * 0.3)
    buf = BytesIO()
    img.save(buf, format="PDF", resolution=float(dpi))
    return buf.getvalue()


@contextmanager
def _view_over(pdf_bytes: bytes):
    """Abre um PDF minúsculo e entrega a `PageView` da primeira página."""
    with opened(pdf_bytes) as pdf:
        yield PageView(pdf, pages_of(pdf, "test")[0], dpi=150)


@pytest.fixture
def scanned_view():
    """Uma página `BORN_DIGITAL` de uma linha, sobre um PDF minúsculo.

    Apesar do nome, não tem raster: é a página com texto que um leitor deve
    aceitar ou recusar. Uma view real em vez de um duplo, para que não possa
    divergir do caminho de produção.
    """
    with _view_over(make_pdf(TEXT_CENTRAL)) as view:
        yield view


@pytest.fixture
def blank_view():
    """Uma página em branco: nenhum leitor pode inventar texto nela."""
    with _view_over(make_pdf(EMPTY_PAGE)) as view:
        yield view
