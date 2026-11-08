# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false
#
# pypdfium2 é um binding C sem stubs, então todo valor que vem dele chega como
# Unknown. A exceção vale só para este módulo, que é a fronteira: tudo o que sai
# daqui para o resto do pacote passa por float(), int() ou um modelo Pydantic, e
# nenhuma API pública expõe Any.
"""Leitura de PDF: páginas, substrato e renderização.

pypdfium2 cobre as três coisas, com licença permissiva (Apache-2.0 / BSD-3).

O que este módulo decide e os outros consomem são dois fatos de cada página.
O substrato diz se a camada de texto foi composta ou reconhecida por OCR, e
orienta a política. `Page.unread` diz quais rasters e desenhos nenhuma camada
leu, e orienta a cascata. Os dois saem do modo em que o texto foi desenhado e
da ordem dos objetos no fluxo da página, sem limiar.
"""

from __future__ import annotations

import ctypes
import hashlib
import io
import math
import re
import threading
import unicodedata
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, override

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from docaudit.types import (
    DOC_ID_HEX_CHARS,
    BBox,
    DocumentError,
    DocumentFacts,
    FormKind,
    Page,
    PageDimensions,
    Region,
    Signature,
    Substrate,
    Turn,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Container, Generator, Sequence

    from PIL import Image

__all__ = [
    "DEFAULT_DPI",
    "MAX_NATIVE_DPI",
    "MIN_NATIVE_DPI",
    "DrawnLine",
    "PageView",
    "RegionView",
    "TextLine",
    "doc_id_for",
    "drawn_lines_of",
    "facts_of",
    "is_image",
    "load_facts",
    "load_pages",
    "opened",
    "pages_of",
    "pdf_of_image",
    "pixels_of",
    "render_of",
    "text_lines_of",
]


class PageView:
    """O conteúdo de uma página de um documento já aberto, carregado sob demanda.

    Guarda o que já entregou, para não renderizar a mesma página duas vezes. O
    ciclo de vida é de uma página só, então nada grande sobrevive à iteração.

    Cada leitor pede só o que usa: a camada de texto não paga renderização, e um
    motor de OCR não paga a extração de linhas.
    """

    regions: Sequence[Region] | None = None
    """Os blocos de layout já detectados na página, para um leitor com o mesmo detector.

    `process(layout=)` os põe na vista da página inteira; um recorte não os tem,
    porque os blocos são da página e o recorte é outra imagem.
    """
    regions_version: str | None = None
    """O `output_version` do detector que produziu `regions`."""

    def __init__(self, pdf: pdfium.PdfDocument, page: Page, *, dpi: int | None = None) -> None:
        """Guarda o documento aberto e a página; nada é lido até alguém pedir."""
        self._pdf = pdf
        self._page = page
        self._dpi = dpi
        self._pixels: dict[bool, Image.Image] = {}
        self._images: dict[bool, bytes] = {}
        self._lines: Sequence[TextLine] | None = None
        self.box: BBox | None = None
        """A caixa do recorte, numa `RegionView`; `None` é a página inteira."""
        self.turn: Turn = 0
        """Graus, no sentido anti-horário, que a vista gira o que mostra."""

    @property
    def page(self) -> Page:
        """A página que esta vista mostra."""
        return self._page

    def pixels(self, *, grayscale: bool = True) -> Image.Image:
        """A página renderizada, no máximo uma vez por modo de cor.

        Cinza por padrão, para um motor que converte para cinza de qualquer
        forma, como o Tesseract. Um leitor treinado em cor, como o PP-OCR e os
        modelos de visão e linguagem, pede RGB. Cada modo é guardado à parte:
        numa cascata em que um leitor pede cinza e o seguinte pede RGB, o
        segundo recebe o que pediu, não o que o primeiro deixou.
        """
        if grayscale not in self._pixels:
            self._pixels[grayscale] = pixels_of(
                self._pdf,
                self._page.index,
                dpi=self._dpi or self._page.dimensions.dpi,
                grayscale=grayscale,
            )
        return self._pixels[grayscale]

    def image(self, *, grayscale: bool = True) -> bytes:
        """PNG de `pixels`, para um leitor que pede o arquivo e não a matriz."""
        if grayscale not in self._images:
            self._images[grayscale] = _png(self.pixels(grayscale=grayscale))
        return self._images[grayscale]

    def text_lines(self) -> Sequence[TextLine]:
        """Linhas do texto embutido, com caixa, lidas no máximo uma vez."""
        if self._lines is None:
            self._lines = text_lines_of(self._pdf, self._page.index)
        return self._lines

    @property
    def rendered(self) -> bool:
        """True se alguém já pediu os pixels desta página."""
        return bool(self._pixels)

    def region(self, box: BBox, *, turn: Turn = 0) -> RegionView:
        """A mesma página vista só dentro de `box`: o que um leitor de pixels lê de um raster.

        Com `turn`, o recorte sai girado esses graus, no sentido anti-horário.
        """
        return RegionView(self, box, turn=turn)


class RegionView(PageView):
    """Uma região de uma página, com o contrato de `PageView`.

    `image()` devolve o recorte da renderização da página, e `page` descreve o
    recorte: as caixas que um leitor devolve são relativas a ele. Quem chama
    as leva de volta à página com `to_page`. A região não tem camada de texto:
    é, por definição, o que nenhuma camada leu.

    `box` é o recorte na página, e `rasters` os rasters de `Page.unread` cujo
    centro cai nele, também na página: é por eles que um leitor decide se a
    região vale a leitura. O raster menor que `process(min_raster_fraction=)`
    nem chega ao leitor.

    Com `turn`, o leitor vê o recorte girado, e `page` tem as dimensões dele
    em pé. `box` e `rasters` seguem no sistema da imagem.
    """

    def __init__(self, parent: PageView, box: BBox, *, turn: Turn = 0) -> None:
        """Guarda a página de origem e a caixa; nada é recortado até alguém pedir."""
        self._parent = parent
        self.box: BBox | None = box
        self.turn: Turn = turn
        self.rasters: tuple[BBox, ...] = tuple(
            r
            for r in parent.page.unread
            if box.x0 <= (r.x0 + r.x1) / 2 <= box.x1 and box.y0 <= (r.y0 + r.y1) / 2 <= box.y1
        )
        dims = parent.page.dimensions
        x0, y0, x1, y1 = box.to_pixels(dims.width_px, dims.height_px)
        width_px, height_px = max(1, x1 - x0), max(1, y1 - y0)
        width_pt = dims.width_pt * width_px / dims.width_px
        height_pt = dims.height_pt * height_px / dims.height_px
        if turn:
            width_px, height_px = height_px, width_px
            width_pt, height_pt = height_pt, width_pt
        self._region_page = parent.page.model_copy(
            update={
                "dimensions": dims.model_copy(
                    update={
                        "width_pt": width_pt,
                        "height_pt": height_pt,
                        "width_px": width_px,
                        "height_px": height_px,
                    }
                ),
                "unread": (),
            }
        )
        self._pixels: dict[bool, Image.Image] = {}
        self._images: dict[bool, bytes] = {}
        self._lines: Sequence[TextLine] | None = ()

    @property
    @override
    def page(self) -> Page:
        """A página do recorte: as dimensões são as do recorte."""
        return self._region_page

    @override
    def pixels(self, *, grayscale: bool = True) -> Image.Image:
        """O recorte, tirado da renderização da página inteira."""
        if grayscale not in self._pixels:
            full = self._parent.pixels(grayscale=grayscale)
            assert self.box is not None
            # A caixa sai do tamanho da imagem renderizada, e não das
            # dimensões da página: um `dpi=` explícito renderiza noutro.
            x0, y0, x1, y1 = self.box.to_pixels(*full.size)
            crop = full.crop((x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)))
            if self.turn:
                crop = crop.rotate(self.turn, expand=True)
            self._pixels[grayscale] = crop
            # As dimensões do recorte são as da imagem que saiu, e não as
            # previstas pela caixa: um `dpi=` explícito renderiza noutro tamanho.
            width_px, height_px = crop.size
            dims = self._region_page.dimensions.model_copy(
                update={"width_px": width_px, "height_px": height_px}
            )
            self._region_page = self._region_page.model_copy(update={"dimensions": dims})
        return self._pixels[grayscale]

    def to_page(self, bbox: BBox) -> BBox:
        """Uma caixa relativa ao recorte, levada à página inteira, no sistema da imagem."""
        assert self.box is not None
        bbox = bbox.unturned(self.turn)
        width, height = self.box.x1 - self.box.x0, self.box.y1 - self.box.y0
        return BBox(
            x0=min(self.box.x0 + bbox.x0 * width, 1.0),
            y0=min(self.box.y0 + bbox.y0 * height, 1.0),
            x1=min(self.box.x0 + bbox.x1 * width, 1.0),
            y1=min(self.box.y0 + bbox.y1 * height, 1.0),
        )


def doc_id_for(document: Path | str | bytes) -> str:
    """Id estável de um documento: SHA-256 dos bytes, 16 hex.

    Lê em blocos quando recebe um caminho: um processo de centenas de MB fica
    inteiro residente antes mesmo de o pdfium abrir o arquivo. Texto é caminho.
    """
    if isinstance(document, str | Path):
        with Path(document).open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()[:DOC_ID_HEX_CHARS]
    return hashlib.sha256(document).hexdigest()[:DOC_ID_HEX_CHARS]


DEFAULT_DPI = 200
"""DPI de renderização de uma página sem raster, quando nenhum é pedido.

Padrão de custo, não recomendação. Uma página com raster é renderizada na
resolução dele, presa a [`MIN_NATIVE_DPI`, `MAX_NATIVE_DPI`].
"""

_MAX_DPI = 1200

MIN_NATIVE_DPI = 150
"""Piso do DPI nativo. Um raster de resolução menor é renderizado no piso.

O valor não tem medida que o separe de outro piso."""

MAX_NATIVE_DPI = 300
"""Teto do DPI nativo. Um raster de resolução maior é renderizado no teto:
300 dpi para todas as páginas custou mais que 200 e não leu melhor."""


_TR_INVISIBLE = 3
"""`Tr 3` do PDF: texto desenhado sem tinta. A assinatura de uma camada de OCR."""

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"})
_IMAGE_MAGIC = (b"\x89PNG", b"\xff\xd8", b"II*\x00", b"MM\x00*", b"BM", b"RIFF")


def is_image(document: Path | bytes) -> bool:
    """True se o documento é uma imagem (PNG, JPEG, TIFF, BMP, WebP), não um PDF.

    Um caminho é julgado pela extensão; bytes, pelos primeiros deles.
    """
    if isinstance(document, Path):
        return document.suffix.lower() in _IMAGE_SUFFIXES
    return document.startswith(_IMAGE_MAGIC)


def pdf_of_image(data: bytes) -> bytes:
    """Embrulha uma imagem num PDF, uma página por quadro, no DPI que ela declara.

    Um JPEG entra como está, sem recomprimir. Os outros formatos entram
    descomprimidos e reempacotados sem perda. Sem DPI declarado, vale o padrão
    de `DEFAULT_DPI`: a folha fica do tamanho que esse DPI dá aos pixels, e a
    classificação recupera o mesmo número do raster embutido.

    É o que permite ler um PNG ou um TIFF de várias páginas com a mesma cascata
    que lê um PDF, sem que nenhum leitor saiba a diferença.
    """
    import zlib

    from PIL import Image, ImageSequence

    with Image.open(io.BytesIO(data)) as img:
        declared = img.info.get("dpi")
        dpi = round(float(declared[0])) if declared else DEFAULT_DPI
        dpi = min(max(dpi, 1), _MAX_DPI)
        raw_jpeg = img.format == "JPEG" and img.mode in ("L", "RGB")
        frames: list[tuple[int, int, str, bytes, bytes]] = []
        for frame in ImageSequence.Iterator(img):
            if raw_jpeg:
                colorspace = "DeviceGray" if img.mode == "L" else "DeviceRGB"
                frames.append((img.width, img.height, colorspace, b"/DCTDecode", data))
                continue
            mode = "L" if frame.mode in ("1", "L", "LA", "I", "I;16") else "RGB"
            pixels = frame.convert(mode)
            colorspace = "DeviceGray" if mode == "L" else "DeviceRGB"
            packed = zlib.compress(pixels.tobytes())
            frames.append((pixels.width, pixels.height, colorspace, b"/FlateDecode", packed))

    objs: list[bytes] = [b"<</Type/Catalog/Pages 2 0 R>>", b""]
    kids: list[str] = []
    for w_px, h_px, colorspace, filter_name, stream in frames:
        w_pt, h_pt = w_px * 72.0 / dpi, h_px * 72.0 / dpi
        page_no = len(objs) + 1
        kids.append(f"{page_no} 0 R")
        content = f"q {w_pt:.4f} 0 0 {h_pt:.4f} 0 0 cm /Im0 Do Q".encode()
        objs.append(
            f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 {w_pt:.4f} {h_pt:.4f}]"
            f"/Contents {page_no + 1} 0 R"
            f"/Resources<</XObject<</Im0 {page_no + 2} 0 R>>>>>>".encode()
        )
        objs.append(b"<</Length %d>>stream\n" % len(content) + content + b"\nendstream")
        header = (
            f"<</Type/XObject/Subtype/Image/Width {w_px}/Height {h_px}/ColorSpace/{colorspace}"
            f"/BitsPerComponent 8/Filter{filter_name.decode()}/Length {len(stream)}>>stream\n"
        )
        objs.append(header.encode() + stream + b"\nendstream")
    objs[1] = f"<</Type/Pages/Kids[{' '.join(kids)}]/Count {len(kids)}>>".encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj" % i + obj + b"endobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def _open(document: Path | str | bytes) -> pdfium.PdfDocument:
    if isinstance(document, str):
        document = Path(document)
    try:
        if is_image(document):
            data = document.read_bytes() if isinstance(document, Path) else document
            pdf = pdfium.PdfDocument(pdf_of_image(data))
        else:
            pdf = pdfium.PdfDocument(document)
    except pdfium.PdfiumError as exc:
        # O pdfium diz "password" na senha errada e "Failed to load" no resto,
        # inclusive num PDF sem página nenhuma.
        if "password" in str(exc).lower():
            raise DocumentError("o PDF está protegido por senha") from exc
        raise DocumentError(f"o arquivo não é um PDF legível: {exc}") from exc
    return pdf


def _all_chars(page: pdfium.PdfPage) -> tuple[int, frozenset[int]]:
    """Caracteres do texto embutido, sem espaços nas pontas, e as fontes sem mapa da página."""
    textpage = page.get_textpage()
    try:
        return len(textpage.get_text_range().strip()), _unmapped_fonts(textpage)
    except pdfium.PdfiumError:
        # Página corrompida: trata como sem texto, que é o lado seguro (vai a OCR).
        # Só PdfiumError, para que um erro de API nosso apareça em vez de virar 0.
        return 0, frozenset()
    finally:
        textpage.close()


_UNMAPPED_SAFE = frozenset({0x0, 0x2, 0x9, 0xA, 0xD})
"""Os códigos abaixo de U+0020 que o pdfium devolve de uma fonte com mapa.

0 é o caractere sem mapeamento, 2 é a marca de hífen de fim de linha, e
tabulação e quebras de linha são do próprio texto. Os demais controles não
são texto impresso.
"""


def _font_key(obj: object) -> int | None:
    """O endereço da fonte de um objeto de texto, que a identifica na página."""
    if not obj:
        return None
    return ctypes.cast(pdfium_c.FPDFTextObj_GetFont(obj), ctypes.c_void_p).value


def _unmapped_fonts(textpage: pdfium.PdfTextPage) -> frozenset[int]:
    """As fontes da página sem mapa para Unicode, pelo endereço.

    Uma fonte embutida sem tabela ToUnicode, num subconjunto com codificação
    Identity, devolve o número do glifo no lugar do caractere. O subconjunto
    numera os glifos a partir de 1, e o texto sai como controles: U+0001,
    U+0003, U+0004. Nenhum texto impresso tem esses códigos. Uma fonte que
    devolve um deles não tem mapa confiável, e nenhum texto dela é leitura:
    os glifos que caem acima de U+0020 saem como letras trocadas, e são
    indistinguíveis de texto. O teste é categórico, por fonte.
    """
    fonts: set[int] = set()
    for i in range(textpage.count_chars()):
        code = pdfium_c.FPDFText_GetUnicode(textpage.raw, i)
        if code >= 0x20 or code in _UNMAPPED_SAFE:
            continue
        key = _font_key(pdfium_c.FPDFText_GetTextObject(textpage.raw, i))
        if key is not None:
            fonts.add(key)
    return frozenset(fonts)


_Box = tuple[float, float, float, float]
"""Uma caixa em pontos do PDF, origem embaixo à esquerda: x0, y0, x1, y1."""


def _page_bounds(obj: pdfium.PdfObject) -> _Box:
    """A caixa de um objeto em coordenadas da página, mesmo dentro de um formulário.

    O pdfium dá a caixa de um objeto aninhado num formulário XObject no espaço
    do formulário. A matriz de cada formulário que o contém leva os quatro
    cantos ao espaço da página; a caixa é a que cerca os cantos levados.
    """
    x0, y0, x1, y1 = (float(v) for v in obj.get_bounds())
    # `container` é o formulário que contém o objeto; o stub não o declara.
    form: pdfium.PdfObject | None = getattr(obj, "container", None)
    if form is None:
        return (x0, y0, x1, y1)
    corners = [(x0, y0), (x0, y1), (x1, y0), (x1, y1)]
    while form is not None:
        a, b, c, d, e, f = (float(v) for v in form.get_matrix().get())
        corners = [(a * x + c * y + e, b * x + d * y + f) for x, y in corners]
        form = getattr(form, "container", None)
    xs = [x for x, _ in corners]
    ys = [y for _, y in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _is_outline(obj: pdfium.PdfObject) -> bool:
    """Um caminho preenchido com curva: o contorno de um glifo, e não a régua de uma tabela.

    A régua e a moldura são segmentos retos; o glifo desenhado em contorno tem
    curvas e é preenchido. O logotipo vetorial também é, e paga um recorte.
    """
    fill, stroke = ctypes.c_int(), ctypes.c_int()
    pdfium_c.FPDFPath_GetDrawMode(obj.raw, ctypes.byref(fill), ctypes.byref(stroke))
    if not fill.value:
        return False
    return any(
        pdfium_c.FPDFPathSegment_GetType(pdfium_c.FPDFPath_GetPathSegment(obj.raw, i))
        == pdfium_c.FPDF_SEGMENT_BEZIERTO
        for i in range(pdfium_c.FPDFPath_CountSegments(obj.raw))
    )


def _inside(inner: _Box, outer: _Box) -> bool:
    return (
        inner[0] >= outer[0]
        and inner[1] >= outer[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _touch(a: _Box, b: _Box) -> bool:
    """Se as duas caixas, fechadas, têm algum ponto em comum: se tocam ou se sobrepõem."""
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


MIN_OUTLINES = 50
"""Quantos contornos de glifo sem texto por cima fazem um corpo desenhado em contornos.

Abaixo disso, os contornos soltos são logotipo, selo ou ícone, e ler não
traz texto. O corte é um parâmetro nomeado, não calibrado aqui.
"""
_CELL = 36.0
"""O lado, em pontos, da grade que indexa as caixas de texto da página."""


def _untouched(boxes: Sequence[_Box], texts: Sequence[_Box]) -> list[_Box]:
    """As caixas de `boxes` que nenhuma de `texts` toca.

    As caixas de texto ficam numa grade, e cada caixa procura só nas células
    que ocupa: a página com milhares de contornos e de textos não vira o
    produto dos dois.
    """
    grid: dict[tuple[int, int], list[_Box]] = {}

    def cells(b: _Box) -> list[tuple[int, int]]:
        xs = range(int(b[0] // _CELL), int(b[2] // _CELL) + 1)
        ys = range(int(b[1] // _CELL), int(b[3] // _CELL) + 1)
        return [(x, y) for x in xs for y in ys]

    for t in texts:
        for cell in cells(t):
            grid.setdefault(cell, []).append(t)
    return [
        b for b in boxes if not any(_touch(b, t) for cell in cells(b) for t in grid.get(cell, ()))
    ]


def merge_touching(rasters: Sequence[tuple[int, _Box]]) -> list[tuple[int, _Box]]:
    """Um raster por grupo de rasters que se tocam: a caixa que envolve o grupo.

    Um scanner, ou o gerador do PDF, grava a digitalização de uma folha em
    ladrilhos, centenas ou milhares de rasters encostados uns nos outros. A
    folha é uma imagem só, e é assim que um leitor de pixels deve vê-la. A
    regra é categórica: duas caixas com um ponto em comum são do mesmo
    grupo, e o grupo cresce até não tocar mais nenhuma. Caixas separadas por
    qualquer vão ficam separadas. O índice do grupo é o maior dos membros,
    o do último desenhado no fluxo, para o teste de texto coberto.
    """
    merged: list[tuple[int, _Box]] = []
    for index, box in rasters:
        while True:
            hit = next((i for i, (_, other) in enumerate(merged) if _touch(box, other)), None)
            if hit is None:
                break
            other_index, other = merged.pop(hit)
            index = max(index, other_index)
            box = (
                min(box[0], other[0]),
                min(box[1], other[1]),
                max(box[2], other[2]),
                max(box[3], other[3]),
            )
        merged.append((index, box))
    return merged


def _hidden_wins(visible: int, invisible: int, covered: int) -> bool:
    """O texto escondido supera o visível: a camada é de uma digitalização."""
    return invisible + covered > visible


class _Objects(NamedTuple):
    """O que uma travessia dos objetos da página devolve."""

    visible: int
    invisible: int
    covered: int
    unmapped: int
    native_dpi: int | None

    @property
    def hidden_layer(self) -> bool:
        """O texto escondido supera o visível: a camada é de uma digitalização."""
        return _hidden_wins(self.visible, self.invisible, self.covered)

    unread: list[_Box]
    hidden_fonts: tuple[str, ...] = ()


def _scan_objects(page: pdfium.PdfPage, unmapped: frozenset[int] = frozenset()) -> _Objects:
    """Conta o texto pelo modo em que foi desenhado e acha os rasters que ninguém leu.

    O modo de desenho é o sinal direto de como o texto chegou ali, e não um
    proxy. Um motor de OCR desenha o texto que reconheceu em modo invisível
    (`Tr 3`) por cima da imagem escaneada, para que a página continue com a
    aparência do original e mesmo assim possa ser buscada. A outra forma de
    esconder uma camada é desenhá-la visível e cobri-la com a imagem, que vem
    depois no fluxo da página: um objeto de texto contido numa imagem
    desenhada depois dele é `covered`. Nenhum dos dois testes tem limiar: ou
    o objeto foi desenhado sem tinta, ou foi coberto, ou não.

    Um raster foi lido quando há texto escondido dentro dele: essa camada é
    a leitura que alguém já fez da imagem. Os rasters que se tocam, os
    ladrilhos de uma digitalização fatiada, são uma imagem só antes desse
    teste (`merge_touching`): a linha da camada atravessa os ladrilhos.
    Texto visível por cima de um raster não o lê: é o rodapé carimbado sobre
    a digitalização, ou a legenda de uma foto. O desenho vetorial da página,
    tomado inteiro, foi lido quando há algum texto dentro dele. Mesmo então,
    os caminhos preenchidos com curva que nenhum texto toca não foram lidos
    quando são ao menos `MIN_OUTLINES`: são o corpo desenhado em contornos
    de glifo, e a caixa que os envolve vai em `unread`. O que não foi lido
    vai em `unread`, e é sobre isso que um leitor de pixels trabalha depois
    da camada de texto.

    O texto numa fonte de `unmapped` não é leitura de nada: não conta como
    texto, e a caixa que envolve esses objetos vai em `unread`, como um
    desenho que ninguém leu. Um leitor de pixels lê os glifos ali.

    A travessia desce nos formulários XObject, onde um gerador costuma pôr a
    tarja lateral ou a digitalização inteira, e leva a caixa de cada objeto
    de lá ao espaço da página.

    A resolução nativa é a do maior raster, em pixels por polegada da página:
    o DPI em que renderizar a página devolve os pixels que existem.
    """
    visible: list[tuple[int, _Box]] = []
    invisible: list[_Box] = []
    images: list[tuple[int, _Box, int]] = []
    paths: list[_Box] = []
    outlines: list[_Box] = []
    glyphs: list[_Box] = []
    # O nome de cada fonte do texto invisível, uma vez por fonte, pelo endereço dela.
    hidden_fonts: dict[int | None, str] = {}
    kinds = (pdfium_c.FPDF_PAGEOBJ_TEXT, pdfium_c.FPDF_PAGEOBJ_IMAGE, pdfium_c.FPDF_PAGEOBJ_PATH)
    for index, obj in enumerate(page.get_objects()):
        if obj.type not in kinds:
            continue
        box = _page_bounds(obj)
        if obj.type == pdfium_c.FPDF_PAGEOBJ_PATH:
            paths.append(box)
            if _is_outline(obj):
                outlines.append(box)
        elif obj.type == pdfium_c.FPDF_PAGEOBJ_TEXT:
            if unmapped and _font_key(obj.raw) in unmapped:
                glyphs.append(box)
            elif pdfium_c.FPDFTextObj_GetTextRenderMode(obj.raw) == _TR_INVISIBLE:
                invisible.append(box)
                key = _font_key(obj.raw)
                if key not in hidden_fonts:
                    hidden_fonts[key] = _font_name(obj.raw)
            else:
                visible.append((index, box))
        else:
            images.append((index, box, int(obj.get_metadata().width)))

    # A folha gravada em ladrilhos é uma imagem só: os testes de leitura valem
    # sobre o grupo, porque uma linha da camada atravessa os ladrilhos.
    rasters = merge_touching([(index, box) for index, box, _ in images])
    covered: list[_Box] = [
        box
        for text_index, box in visible
        if any(img_index > text_index and _inside(box, img) for img_index, img in rasters)
    ]
    # O texto coberto só lê o raster quando é a camada da página, o mesmo
    # juízo que decide o substrato. Numa página de texto visível, o texto
    # coberto é o número de folha carimbado antes da digitalização, e um
    # carimbo não lê o corpo.
    hidden_layer = _hidden_wins(len(visible) - len(covered), len(invisible), len(covered))
    layer = invisible + covered if hidden_layer else invisible
    unread = [img for _, img in rasters if not any(_inside(h, img) for h in layer)]
    if paths:
        # O desenho vetorial é lido quando há texto dentro dele: as linhas de
        # uma tabela cercam o texto das células. Sem texto dentro, é um
        # logotipo, um traço de assinatura, ou o corpo inteiro desenhado em
        # contornos de glifo, e só um leitor de pixels o lê.
        drawing = (
            min(b[0] for b in paths),
            min(b[1] for b in paths),
            max(b[2] for b in paths),
            max(b[3] for b in paths),
        )
        texts = [box for _, box in visible] + invisible
        if not any(_inside(t, drawing) for t in texts):
            unread.append(drawing)
        elif len(outlines) >= MIN_OUTLINES:
            # Com texto no desenho, o contorno de glifo que nenhum texto toca
            # continua sem leitura: o corpo desenhado em contornos sob uma tarja
            # ou um cabeçalho de texto. O fundo arredondado de uma célula toca
            # o texto dela e fica lido.
            bare = _untouched(outlines, texts)
            if len(bare) >= MIN_OUTLINES:
                unread.append(
                    (
                        min(b[0] for b in bare),
                        min(b[1] for b in bare),
                        max(b[2] for b in bare),
                        max(b[3] for b in bare),
                    )
                )

    if glyphs:
        unread.append(
            (
                min(b[0] for b in glyphs),
                min(b[1] for b in glyphs),
                max(b[2] for b in glyphs),
                max(b[3] for b in glyphs),
            )
        )

    native_dpi: int | None = None
    if images:
        _, (x0, _y0, x1, _y1), pixels = max(
            images, key=lambda t: (t[1][2] - t[1][0]) * (t[1][3] - t[1][1])
        )
        if x1 > x0:
            native_dpi = round(pixels / ((x1 - x0) / 72.0))
    return _Objects(
        visible=len(visible) - len(covered),
        invisible=len(invisible),
        covered=len(covered),
        unmapped=len(glyphs),
        native_dpi=native_dpi,
        unread=unread,
        hidden_fonts=tuple(dict.fromkeys(filter(None, hidden_fonts.values()))),
    )


_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")


def _font_name(obj: object) -> str:
    """O nome base da fonte de um objeto de texto, sem o prefixo de subconjunto `ABCDEF+`."""
    font = pdfium_c.FPDFTextObj_GetFont(obj)
    name = _ascii_of(pdfium_c.FPDFFont_GetBaseFontName, font) if font else None
    return _SUBSET_PREFIX.sub("", name or "")


def _displayed(page: pdfium.PdfPage) -> Callable[[_Box], BBox]:
    """Leva uma caixa em pontos do espaço da página para a folha como ela é exibida.

    O espaço da página tem origem embaixo, no canto da caixa visível, que nem
    sempre é (0, 0); e a página pode ser exibida girada (`/Rotate`). A imagem
    renderizada é a da página exibida, e é nela que a caixa normalizada tem de
    cair, com origem no canto superior esquerdo.
    """
    left, bottom, right, top = (float(v) for v in page.get_bbox())
    width, height = right - left, top - bottom
    turn = page.get_rotation() % 360

    def unit(x: float, y: float) -> tuple[float, float]:
        u, v = (x - left) / width, (top - y) / height
        # `/Rotate` gira a página no sentido horário ao exibi-la.
        if turn == 90:
            return 1 - v, u
        if turn == 180:
            return 1 - u, 1 - v
        if turn == 270:
            return v, 1 - u
        return u, v

    def convert(box: _Box) -> BBox:
        x0, y0, x1, y1 = box
        (a, b), (c, d) = unit(x0, y1), unit(x1, y0)
        return BBox.from_pixels(
            min(a, c), min(b, d), max(a, c), max(b, d), width_px=1.0, height_px=1.0
        )

    return convert


def _substrate_of(
    page: pdfium.PdfPage,
) -> tuple[Substrate, dict[str, float], tuple[BBox, ...], tuple[str, ...]]:
    """Classifica uma página pela camada de texto e devolve o que nenhuma camada leu.

    Recebe uma página de posse do chamador, com o lock já tomado.

    O substrato é um fato da camada de texto, e responde a duas perguntas,
    em ordem. Há texto embutido? Sem ele, `IMAGE_ONLY`. O texto está mais
    escondido que à vista? Então a camada foi inserida sobre uma
    digitalização, `SEARCHABLE_SCAN`. O que sobra é texto à vista,
    `BORN_DIGITAL`.

    Se a página tem pixels que ninguém leu é o outro fato, e não entra na
    classe: os rasters sem camada vão nas caixas devolvidas. Uma folha
    digitalizada com a tarja do e-SAJ na margem tem camada à vista, a tarja,
    e um raster sem leitura, o corpo. É `BORN_DIGITAL`, com o corpo nas
    caixas devolvidas.

    O texto numa fonte sem mapa para Unicode (`_unmapped_fonts`) fica fora
    das contagens, e a área dele vai nas caixas devolvidas. Uma página
    inteira nessa fonte é `BORN_DIGITAL` sem linha alguma na camada.

    Returns:
        O substrato, os números crus que o sustentaram, as caixas dos
        rasters que nenhuma camada de texto leu, normalizadas, e os nomes
        das fontes do texto invisível.
    """
    chars, unmapped = _all_chars(page)
    objects = _scan_objects(page, unmapped)
    displayed = _displayed(page)
    # De cima para baixo e da esquerda para a direita: a ordem é da geometria,
    # não da ordem dos objetos no fluxo da página, e o índice é estável.
    unread = tuple(sorted((displayed(b) for b in objects.unread), key=lambda b: (b.y0, b.x0)))
    evidence = {
        "chars": float(chars),
        "visible_text": float(objects.visible),
        "invisible_text": float(objects.invisible),
        "covered_text": float(objects.covered),
        "unmapped_text": float(objects.unmapped),
        "unread_regions": float(len(unread)),
    }
    if objects.native_dpi is not None:
        evidence["native_dpi"] = float(objects.native_dpi)
    if chars == 0:
        substrate = Substrate.IMAGE_ONLY
    elif objects.hidden_layer:
        substrate = Substrate.SEARCHABLE_SCAN
    else:
        substrate = Substrate.BORN_DIGITAL
    return substrate, evidence, unread, objects.hidden_fonts


_PDFIUM = threading.Lock()
"""Serializa todo acesso ao pdfium, inclusive fechar as páginas.

O pdfium não é seguro para uso concorrente: duas threads abrindo um documento
ou carregando uma página falham com `Failed to load page`, ou corrompem em
silêncio. Um lock basta, sem pool de processos, porque o OCR, que domina o
tempo de uma página, roda fora dele.
"""


@contextmanager
def _locked_page(pdf: pdfium.PdfDocument, index: int) -> Generator[pdfium.PdfPage, None, None]:
    """Abre uma página sob o lock e a fecha antes de soltá-lo.

    `PdfPage` tem finalizador: deixar a coleta fechar a página pode chamar o
    pdfium de outra thread, fora do lock. Toda página aberta aqui é fechada
    aqui.
    """
    with _PDFIUM:
        page = pdf[index]
        try:
            yield page
        finally:
            page.close()


@contextmanager
def opened(document: Path | str | bytes) -> Generator[pdfium.PdfDocument, None, None]:
    """Abre o documento uma vez e o entrega aberto.

    Abrir um PDF custa o parse do trailer e da árvore de páginas. Quem processa
    um documento inteiro abre uma vez aqui e passa o documento aberto adiante.
    """
    with _PDFIUM:
        pdf = _open(document)
    try:
        yield pdf
    finally:
        with _PDFIUM:
            pdf.close()


def pages_of(
    pdf: pdfium.PdfDocument,
    doc_id: str,
    *,
    dpi: int | None = None,
    only: Container[int] | None = None,
) -> list[Page]:
    """Metadados e substrato das páginas de um documento já aberto.

    `only` restringe a quais índices; as demais nem chegam a ser carregadas.

    O DPI de cada página é o nativo do raster dela, preso a
    [`MIN_NATIVE_DPI`, `MAX_NATIVE_DPI`], quando há raster; senão o padrão.
    Passar `dpi` fixa um valor para todas.
    """
    scale_all = (dpi or DEFAULT_DPI) / 72.0
    out: list[Page] = []
    for i in range(len(pdf)):
        if only is not None and i not in only:
            continue
        with _locked_page(pdf, i) as page:
            w, h = float(page.get_width()), float(page.get_height())
            substrate, evidence, unread, hidden_fonts = _substrate_of(page)
        native = evidence.get("native_dpi")
        use_dpi = (
            min(max(int(native), MIN_NATIVE_DPI), MAX_NATIVE_DPI)
            if dpi is None and native is not None
            else int(scale_all * 72.0)
        )
        scale = use_dpi / 72.0
        out.append(
            Page(
                doc_id=doc_id,
                index=i,
                dimensions=PageDimensions(
                    width_pt=w,
                    height_pt=h,
                    # `ceil`, como o pdfium ao rasterizar: estas são as
                    # dimensões da imagem que a renderização produz, e uma
                    # caixa normalizada por elas cai no pixel certo.
                    width_px=max(1, math.ceil(w * scale)),
                    height_px=max(1, math.ceil(h * scale)),
                    dpi=use_dpi,
                ),
                substrate=substrate,
                substrate_evidence=evidence,
                unread=unread,
                hidden_fonts=hidden_fonts,
            )
        )
    return out


# ── O que o arquivo diz de si ───────────────────────────────────────────────

_PDF_DATE = re.compile(
    r"D?:?(?P<year>\d{4})(?P<month>\d{2})?(?P<day>\d{2})?(?P<hour>\d{2})?(?P<minute>\d{2})?"
    r"(?P<second>\d{2})?(?:(?P<sign>[+\-Z])(?P<tz_hour>\d{2})?'?(?P<tz_minute>\d{2})?'?)?"
)
_FORM_TYPES: dict[int, FormKind] = {0: "none", 1: "acroform", 2: "xfa_full", 3: "xfa_foreground"}
_ALL_PERMISSIONS = 0xFFFFFFFF


def _pdf_date(text: str | None) -> datetime | None:
    """A data de um PDF, `D:AAAAMMDDhhmmss+hh'mm'`, com o fuso; `None` sem data ou mal formada."""
    if not text:
        return None
    match = _PDF_DATE.match(text.strip())
    if match is None:
        return None
    parts = match.groupdict()
    try:
        when = datetime(
            int(parts["year"]),
            int(parts["month"] or 1),
            int(parts["day"] or 1),
            int(parts["hour"] or 0),
            int(parts["minute"] or 0),
            int(parts["second"] or 0),
        )
    except ValueError:
        return None
    sign = parts["sign"]
    if sign in ("+", "-"):
        offset = timedelta(hours=int(parts["tz_hour"] or 0), minutes=int(parts["tz_minute"] or 0))
        return when.replace(tzinfo=timezone(-offset if sign == "-" else offset))
    if sign == "Z":
        return when.replace(tzinfo=UTC)
    return when


def _ascii_of(fn: Callable[..., int], *args: object) -> str | None:
    """Uma cadeia ASCII que o pdfium devolve em duas chamadas: o tamanho, depois o conteúdo."""
    size = fn(*args, None, 0)
    if size <= 1:
        return None
    buffer = ctypes.create_string_buffer(size)
    fn(*args, buffer, size)
    return buffer.raw.rstrip(b"\x00").decode("latin-1", "replace") or None


def _wide_of(fn: Callable[..., int], *args: object) -> str | None:
    """Uma cadeia UTF-16 que o pdfium devolve em duas chamadas, em bytes."""
    size = fn(*args, None, 0)
    if size <= 2:
        return None
    buffer = ctypes.create_string_buffer(size)
    fn(*args, buffer, size)
    return buffer.raw[: size - 2].decode("utf-16-le", "replace") or None


def _signatures_of(pdf: pdfium.PdfDocument, file_size: int | None) -> tuple[Signature, ...]:
    out: list[Signature] = []
    for i in range(pdfium_c.FPDF_GetSignatureCount(pdf.raw)):
        sig = pdfium_c.FPDF_GetSignatureObject(pdf.raw, i)
        count = pdfium_c.FPDFSignatureObj_GetByteRange(sig, None, 0)
        covers = False
        if count >= 4 and file_size is not None:
            ranges = (ctypes.c_int * count)()
            pdfium_c.FPDFSignatureObj_GetByteRange(sig, ranges, count)
            covers = int(ranges[count - 2]) + int(ranges[count - 1]) == file_size
        out.append(
            Signature(
                sub_filter=_ascii_of(pdfium_c.FPDFSignatureObj_GetSubFilter, sig),
                signed_at=_pdf_date(_ascii_of(pdfium_c.FPDFSignatureObj_GetTime, sig)),
                reason=_wide_of(pdfium_c.FPDFSignatureObj_GetReason, sig),
                mdp_permission=int(pdfium_c.FPDFSignatureObj_GetDocMDPPermission(sig)),
                covers_file=covers,
            )
        )
    return tuple(out)


_SCAN_BLOCK = 1 << 20


def _file_scan(document: Path | bytes) -> tuple[int, int, bool]:
    """O tamanho do arquivo, quantos `startxref` ele tem e se está linearizado.

    Cada gravação termina num `startxref`, e é por ele que se contam as
    gravações: o pdfium não devolve os trailers de uma tabela xref clássica.
    Um arquivo linearizado tem um trailer a mais, o da primeira página, que
    não é gravação. O arquivo é lido em blocos, com a palavra que pode
    partir entre dois blocos contada uma vez só.
    """
    handle = io.BytesIO(document) if isinstance(document, bytes) else document.open("rb")
    with handle:
        block = handle.read(1024)
        linearized = b"/Linearized" in block
        size = count = 0
        tail = b""
        while block:
            # A palavra partida entre dois blocos aparece só na costura dos 8 bytes de cada lado.
            count += block.count(b"startxref") + (tail + block[:8]).count(b"startxref")
            tail = block[-8:]
            size += len(block)
            block = handle.read(_SCAN_BLOCK)
    return size, count, linearized


def facts_of(pdf: pdfium.PdfDocument, *, file: Path | str | bytes | None = None) -> DocumentFacts:
    """O que um documento já aberto diz de si: metadados, versão, gravações e assinaturas.

    `file` é o arquivo de onde o documento veio, para contar as gravações e
    saber se uma assinatura cobre o arquivo inteiro; sem ele, `saves` sai
    `None` e `covers_file` sai `False`. Uma imagem não tem o que contar. O resto
    vem do trailer, do catálogo e do dicionário de informações: nada é
    renderizado.
    """
    file_size: int | None = None
    saves: int | None = None
    if file is not None:
        source = Path(file) if isinstance(file, str) else file
        if not is_image(source):
            file_size, trailers, linearized = _file_scan(source)
            saves = max(1, trailers - (1 if linearized else 0))
    with _PDFIUM:
        meta = pdf.get_metadata_dict()
        version = pdf.get_version()
        permanent = pdf.get_identifier(pdfium_c.FILEIDTYPE_PERMANENT)
        changing = pdf.get_identifier(pdfium_c.FILEIDTYPE_CHANGING)
        return DocumentFacts(
            producer=meta.get("Producer") or None,
            creator=meta.get("Creator") or None,
            title=meta.get("Title") or None,
            author=meta.get("Author") or None,
            subject=meta.get("Subject") or None,
            keywords=meta.get("Keywords") or None,
            created_at=_pdf_date(meta.get("CreationDate")),
            modified_at=_pdf_date(meta.get("ModDate")),
            pdf_version=f"{version // 10}.{version % 10}" if version else None,
            tagged=bool(pdf.is_tagged()),
            form=_FORM_TYPES.get(int(pdf.get_formtype()), "none"),
            saves=saves,
            identifier_changed=(permanent != changing) if permanent else None,
            restricted=int(pdfium_c.FPDF_GetDocPermissions(pdf.raw)) != _ALL_PERMISSIONS,
            page_labels=bool(len(pdf) and pdf.get_page_label(0)),
            signatures=_signatures_of(pdf, file_size),
        )


def load_facts(document: Path | str | bytes) -> DocumentFacts:
    """O que o arquivo diz de si, sem classificar nem renderizar página nenhuma."""
    with opened(document) as pdf:
        return facts_of(pdf, file=document)


_LINE_BREAKS = frozenset("\r\n")
_HYPHEN_MARK = 0x2
"""O código com que o pdfium marca um hífen de fim de linha entre letras."""
_SYMBOL_BULLET = 0xF0B7
"""O marcador de lista que o Word desenha com a fonte Symbol, na área de uso privado."""


class _Glyph(NamedTuple):
    """Um caractere desenhado: a caixa justa, a caixa da fonte e o ângulo da escrita."""

    box: _Box
    loose: _Box
    angle: float


def _visual_order(chars: Sequence[str], glyphs: Sequence[_Glyph | None]) -> str | None:
    """A linha na ordem da folha, da esquerda para a direita, quando o arquivo a desenhou noutra.

    O pdfium monta a linha na ordem em que o arquivo desenha o texto. Uma
    planilha exportada desenha `R$ 17,86` num objeto que cobre também o
    número da célula vizinha, e a linha sai `R$ 17,86 23,81 R$`: o `R$` não
    fica antes do número dele. A palavra é o trecho entre espaços, e as
    palavras voltam na ordem do x.

    Devolve `None`, e a linha fica como o arquivo a desenhou, quando ela já
    está na ordem do x, quando algum caractere está girado (a tarja vertical
    de um tribunal é escrita de baixo para cima), ou quando a linha junta
    palavras de mais de uma fileira da folha: o nome que quebra em duas
    fileiras numa célula fica na linha do id dele.
    """
    words: list[tuple[str, float, float]] = []
    run: list[int] = []

    def close() -> None:
        if run:
            looses = [g.loose for j in run if (g := glyphs[j]) is not None]
            left = min(g.box[0] for j in run if (g := glyphs[j]) is not None)
            centre = (min(b[1] for b in looses) + max(b[3] for b in looses)) / 2
            words.append(("".join(chars[j] for j in run), left, centre))
            run.clear()

    for j, glyph in enumerate(glyphs):
        if glyph is None:
            close()
            continue
        if glyph.angle != 0.0:
            return None
        run.append(j)
    close()
    if len(words) < 2 or all(a[1] <= b[1] for a, b in pairwise(words)):
        return None
    # Uma fileira só: o centro de cada palavra cai na caixa da fonte da primeira.
    first = next(g for g in glyphs if g is not None)
    if not all(first.loose[1] <= w[2] <= first.loose[3] for w in words):
        return None
    return " ".join(w[0] for w in sorted(words, key=lambda w: w[1]))


class TextLine(NamedTuple):
    """Uma linha do texto embutido: a caixa, o texto e onde ele tinha hífen de fim de linha."""

    bbox: BBox
    text: str
    hyphens: tuple[int, ...]
    """Índices em `text` dos hífens que estavam numa quebra de linha do PDF."""


class DrawnLine(NamedTuple):
    """Uma linha da camada, a posição dela na ordem de desenho e se ela está à vista."""

    line: TextLine
    drawn: int
    """A posição, na ordem de desenho, do primeiro objeto de texto da linha; -1 sem objeto."""
    visible: bool
    """Desenhada com tinta e sem imagem desenhada depois por cima, o mesmo juízo do substrato."""


def _drawing_of(page: pdfium.PdfPage) -> dict[int, tuple[int, bool]]:
    """Por endereço de objeto de texto, a posição dele no desenho e se ele está à vista.

    A posição conta todos os objetos, também os de dentro dos formulários, na
    ordem em que a página os desenha. À vista é o texto com tinta que nenhuma
    imagem desenhada depois cobre: o mesmo juízo de `_objects`.
    """
    texts: list[tuple[int, int, _Box, bool]] = []
    images: list[tuple[int, _Box]] = []
    for index, obj in enumerate(page.get_objects()):
        if obj.type == pdfium_c.FPDF_PAGEOBJ_TEXT:
            inked = pdfium_c.FPDFTextObj_GetTextRenderMode(obj.raw) != _TR_INVISIBLE
            address = ctypes.cast(obj.raw, ctypes.c_void_p).value or 0
            texts.append((address, index, _page_bounds(obj), inked))
        elif obj.type == pdfium_c.FPDF_PAGEOBJ_IMAGE:
            images.append((index, _page_bounds(obj)))
    rasters = merge_touching(images)
    return {
        address: (
            index,
            inked and not any(j > index and _inside(box, img) for j, img in rasters),
        )
        for address, index, box, inked in texts
    }


def text_lines_of(pdf: pdfium.PdfDocument, index: int) -> list[TextLine]:
    """Linhas do texto embutido de uma página, na ordem do texto do pdfium; ver `drawn_lines_of`."""
    return [drawn.line for drawn in drawn_lines_of(pdf, index)]


def drawn_lines_of(pdf: pdfium.PdfDocument, index: int) -> list[DrawnLine]:
    """Linhas do texto embutido de uma página, com a caixa de cada uma e os hífens de quebra.

    A linha é a que o pdfium monta, e não o retângulo cru: um gerador que posiciona cada
    letra isoladamente produz um retângulo por letra: "Banco" vira cinco trechos,
    e nenhum extrator que leia trecho a trecho encontra a palavra.

    A caixa é a união das caixas dos caracteres desenhados da linha. Espaços e
    caracteres que o pdfium gera, sem glifo, não entram nela. O pdfium trabalha
    em pontos com origem no canto inferior esquerdo; a saída é normalizada com
    origem no canto superior esquerdo, que é a convenção do `BBox`.

    O texto sai em NFC. Uma fonte pode mapear "ç" para "c" seguido do cedilha
    combinante; as duas formas são o mesmo texto pelo Unicode, mas só a
    composta casa com uma busca por "ç". A forma de compatibilidade (NFKC) não
    entra, porque troca "nº" por "no" e "m²" por "m2".

    Dois códigos que nenhum texto impresso tem saem como o caractere que a
    página mostra. O pdfium marca com U+0002 o hífen que fica numa quebra de
    linha entre letras, e junta as duas linhas visuais numa só; ele volta como
    o `-` impresso, e o índice dele fica em `hyphens`, porque o pdfium não
    distingue o hífen de translineação do hífen de uma URL ou de um nome
    composto partido na margem. Juntar as metades é decisão de quem lê, com
    o índice à mão; apagar o hífen não teria volta. O marcador de lista que o
    Word desenha com a fonte Symbol vem na área de uso privado, U+F0B7, e sai
    como "•".

    A linha que é uma fileira da folha sai da esquerda para a direita,
    mesmo quando o arquivo desenha os pedaços dela noutra ordem
    (`_visual_order`). A linha com hífen de fim de linha marcado, a que junta
    mais de uma fileira e o texto girado ficam como o arquivo os desenhou.

    O texto numa fonte sem mapa para Unicode (`_unmapped_fonts`) não sai:
    é o número de cada glifo, não o caractere. A área dele vai em
    `Page.unread`, e um leitor de pixels a lê.

    Cada linha vem com a posição, na ordem de desenho da página, do primeiro
    objeto de texto dela, contando os objetos de dentro dos formulários, e
    com se ela está à vista (`DrawnLine`). A ordem das linhas é a do texto
    do pdfium, e nem sempre é a do desenho: o carimbo posto por cima de
    outro, como a folha do tribunal sobre a da cópia, vem depois só na ordem
    de desenho. Numa digitalização com camada de OCR, a linha à vista é a
    que o produtor desenhou com tinta por cima, como a tarja do tribunal; a
    camada do OCR é invisível ou fica sob a imagem.
    """
    with _locked_page(pdf, index) as page:
        if float(page.get_width()) <= 0 or float(page.get_height()) <= 0:
            return []
        displayed = _displayed(page)
        drawing = _drawing_of(page)
        out: list[DrawnLine] = []
        with closing(page.get_textpage()) as textpage:
            unmapped = _unmapped_fonts(textpage)
            chars: list[str] = []
            glyphs: list[_Glyph | None] = []
            marks: set[int] = set()
            box: tuple[float, float, float, float] | None = None
            first: list[tuple[int, bool]] = []

            def flush() -> None:
                drawn = min(at for at, _ in first) if first else -1
                visible = bool(first) and all(v for _, v in first)
                ordered = None if marks else _visual_order(chars, glyphs)
                if ordered is not None:
                    text_value = unicodedata.normalize("NFC", ordered).strip()
                    if text_value and box is not None:
                        line = TextLine(displayed(box), text_value, ())
                        out.append(DrawnLine(line, drawn, visible))
                    return
                # Cada trecho entre hífens marcados é normalizado à parte: o NFC
                # pode encurtar um trecho ("c" mais cedilha vira "ç"), e o índice
                # do hífen tem de valer no texto que sai.
                parts: list[str] = []
                current: list[str] = []
                for j, ch in enumerate(chars):
                    if j in marks:
                        parts.append(unicodedata.normalize("NFC", "".join(current)))
                        current = []
                    else:
                        current.append(ch)
                parts.append(unicodedata.normalize("NFC", "".join(current)))
                joined = "-".join(parts)
                text_value = joined.strip()
                lead = len(joined) - len(joined.lstrip())
                hyphens: list[int] = []
                position = 0
                for part in parts[:-1]:
                    position += len(part)
                    hyphens.append(position - lead)
                    position += 1
                if text_value and box is not None:
                    inside = tuple(h for h in hyphens if 0 <= h < len(text_value))
                    out.append(
                        DrawnLine(TextLine(displayed(box), text_value, inside), drawn, visible)
                    )

            high = 0
            for i in range(textpage.count_chars()):
                if unmapped and (
                    _font_key(pdfium_c.FPDFText_GetTextObject(textpage.raw, i)) in unmapped
                ):
                    continue
                code = pdfium_c.FPDFText_GetUnicode(textpage.raw, i)
                # A tabela ToUnicode é UTF-16BE (ISO 32000-1, 9.10.3), e o pdfium
                # devolve uma unidade por vez. Um caractere fora do plano básico,
                # como as letras matemáticas em negrito, vem em duas metades, e só
                # as duas juntas formam o caractere. 0 é caractere sem mapeamento;
                # uma metade solta não é caractere.
                if 0xD800 <= code <= 0xDBFF:
                    high = code
                    continue
                if 0xDC00 <= code <= 0xDFFF and high:
                    code = 0x10000 + ((high - 0xD800) << 10) + (code - 0xDC00)
                high = 0
                if code == 0 or 0xD800 <= code <= 0xDFFF:
                    continue
                if code == _HYPHEN_MARK:
                    marks.add(len(chars))
                    char = "-"
                elif code == _SYMBOL_BULLET:
                    char = "\u2022"
                else:
                    char = chr(code)
                if char in _LINE_BREAKS:
                    flush()
                    chars, glyphs, marks, box, first = [], [], set(), None, []
                    continue
                chars.append(char)
                obj = pdfium_c.FPDFText_GetTextObject(textpage.raw, i)
                if (at := drawing.get(ctypes.cast(obj, ctypes.c_void_p).value or 0)) is not None:
                    first.append(at)
                if char.isspace() or pdfium_c.FPDFText_IsGenerated(textpage.raw, i) == 1:
                    glyphs.append(None)
                    continue
                left, bottom, right, top = textpage.get_charbox(i)
                # A caixa da fonte dá a altura da fileira: a justa de um
                # caractere pode ter altura zero.
                l0, b0, r0, t0 = textpage.get_charbox(i, loose=True)
                glyphs.append(
                    _Glyph(
                        (left, bottom, right, top),
                        (float(l0), float(b0), float(r0), float(t0)),
                        float(pdfium_c.FPDFText_GetCharAngle(textpage.raw, i)),
                    )
                )
                box = (
                    (left, bottom, right, top)
                    if box is None
                    else (
                        min(box[0], left),
                        min(box[1], bottom),
                        max(box[2], right),
                        max(box[3], top),
                    )
                )
            flush()
        return out


def pixels_of(
    pdf: pdfium.PdfDocument, index: int, *, dpi: int | None = None, grayscale: bool = False
) -> Image.Image:
    """Renderiza uma página de um documento já aberto.

    `grayscale` serve a um motor que converte para cinza de qualquer forma,
    como o Tesseract: mandar RGB a ele paga a conversão mais o triplo de
    pixels. Um leitor treinado em cor pede RGB.
    """
    # O stub de pypdfium2 declara scale: int, mas a função aceita float e é
    # assim que se renderiza em DPI arbitrário.
    scale = (dpi or DEFAULT_DPI) / 72.0
    with _locked_page(pdf, index) as page:
        bitmap = page.render(scale=scale, grayscale=grayscale)  # pyright: ignore[reportArgumentType]
        with closing(bitmap):
            # Em cinza, o Pillow aponta para o buffer do bitmap em vez de copiar;
            # em RGB ele copia ao reordenar os canais. A cópia solta a imagem do
            # bitmap, e o `closing` destrói o bitmap aqui, sob o lock, em vez de
            # deixá-lo para o coletor, que o destruiria de qualquer thread.
            image = bitmap.to_pil()
            return image.copy() if grayscale else image


def render_of(
    pdf: pdfium.PdfDocument, index: int, *, dpi: int | None = None, grayscale: bool = False
) -> bytes:
    """`pixels_of` como PNG."""
    # A codificação do PNG é Pillow puro e não toca no pdfium: fica fora do lock.
    return _png(pixels_of(pdf, index, dpi=dpi, grayscale=grayscale))


def _png(image: Image.Image) -> bytes:
    """A imagem codificada como PNG, sem perda."""
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def load_pages(document: Path | str | bytes, *, dpi: int | None = None) -> list[Page]:
    """Metadados e substrato de cada página, sem renderizar nada.

    O DPI entra só para preencher as dimensões em pixel que a renderização
    produziria; nenhuma imagem é gerada aqui.
    """
    with opened(document) as pdf:
        return pages_of(pdf, doc_id_for(document), dpi=dpi)
