# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tipos de dados públicos.

Todos são `BaseModel` congelados: atravessam fronteiras de serialização (o cache,
o JSON de saída) e a validação na construção pega erros de backend cedo.
"""

from __future__ import annotations

import functools
import hashlib
import itertools
import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic import Field as PField

if TYPE_CHECKING:
    from docaudit.pdf import PageView
    from docaudit.policies import FailsCheck, Signal

__all__ = [
    "DOC_ID_HEX_CHARS",
    "ID_HEX_CHARS",
    "SCHEMA_HEX_CHARS",
    "BBox",
    "Budget",
    "Chunk",
    "DocumentError",
    "DocumentFacts",
    "Entity",
    "EntityState",
    "ExternalBackendError",
    "Figure",
    "Folha",
    "FormKind",
    "Layout",
    "Metered",
    "OtherReading",
    "Page",
    "PageDimensions",
    "Piece",
    "Reader",
    "Record",
    "Region",
    "Reread",
    "Result",
    "RoutingDecision",
    "Run",
    "Signature",
    "Spent",
    "Stamp",
    "Substrate",
    "Tier",
    "TriagePolicy",
    "TrustLayer",
    "chunk_schema_digest",
    "reading_order_key",
]


ID_HEX_CHARS = 24
"""Dígitos hexadecimais de um `Chunk.id`: 96 bits de SHA-256."""

SCHEMA_HEX_CHARS = 12
"""Dígitos do digest de esquema."""

DOC_ID_HEX_CHARS = 16
"""Dígitos hexadecimais de um `doc_id`: 64 bits."""

type TrustLayer = Literal["visible", "always"]
"""O que fazer com a camada de texto que um OCR desconhecido deixou sob a imagem."""

type Reread = Literal["page", "region"]
"""O que o leitor caro recebe de uma página encaminhada: a página inteira ou um recorte."""

type Turn = Literal[0, 90, 270]
"""Graus, no sentido anti-horário, que uma página ou uma vista dela é girada."""

type FormKind = Literal["none", "acroform", "xfa_full", "xfa_foreground"]
"""O tipo de formulário de um PDF: nenhum, AcroForm, ou XFA inteiro ou de primeiro plano."""


@functools.cache
def chunk_schema_digest() -> str:
    """Digest dos campos de `Chunk`, derivado do próprio modelo.

    Entra na chave do cache: mudar o modelo invalida as entradas antigas em vez
    de deixá-las ser lidas com os campos preenchidos por omissão.

    Returns:
        Os primeiros `SCHEMA_HEX_CHARS` dígitos de um SHA-256 dos campos.
    """
    fields = ";".join(f"{n}:{f.annotation}" for n, f in sorted(Chunk.model_fields.items()))
    return hashlib.sha256(fields.encode()).hexdigest()[:SCHEMA_HEX_CHARS]


class ExternalBackendError(RuntimeError):
    """Um leitor que sai da máquina foi pedido sem autorização explícita."""


class DocumentError(ValueError):
    """O documento não pode ser aberto: senha, ou arquivo que o pdfium não lê como PDF."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BBox(_Frozen):
    """Caixa normalizada: coordenadas em [0, 1], origem no canto superior esquerdo."""

    x0: float = PField(ge=0.0, le=1.0)
    y0: float = PField(ge=0.0, le=1.0)
    x1: float = PField(ge=0.0, le=1.0)
    y1: float = PField(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> BBox:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bbox com cantos invertidos")
        return self

    @property
    def area(self) -> float:
        """Área da caixa no espaço normalizado."""
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    def intersection(self, other: BBox) -> float:
        """A área da interseção com outra caixa; 0 quando não se tocam."""
        width = min(self.x1, other.x1) - max(self.x0, other.x0)
        height = min(self.y1, other.y1) - max(self.y0, other.y0)
        return max(width, 0.0) * max(height, 0.0)

    def key(self) -> str:
        """A caixa como texto, com quatro casas: entra nos ids e nas chaves do cache."""
        return f"{self.x0:.4f},{self.y0:.4f},{self.x1:.4f},{self.y1:.4f}"

    def to_pixels(self, width_px: int, height_px: int) -> tuple[int, int, int, int]:
        """Desnormaliza para pixels de uma renderização concreta."""
        return (
            round(self.x0 * width_px),
            round(self.y0 * height_px),
            round(self.x1 * width_px),
            round(self.y1 * height_px),
        )

    def padded(self, margin: float) -> BBox:
        """A caixa com `margin` de folga em cada lado, presa à folha."""
        return BBox(
            x0=max(self.x0 - margin, 0.0),
            y0=max(self.y0 - margin, 0.0),
            x1=min(self.x1 + margin, 1.0),
            y1=min(self.y1 + margin, 1.0),
        )

    def unturned(self, turn: int) -> BBox:
        """A caixa de uma página girada `turn` graus (anti-horário), no sistema da imagem."""
        if turn == 90:
            return BBox(x0=1.0 - self.y1, y0=self.x0, x1=1.0 - self.y0, y1=self.x1)
        if turn == 270:
            return BBox(x0=self.y0, y0=1.0 - self.x1, x1=self.y1, y1=1.0 - self.x0)
        return self

    @classmethod
    def envelope(cls, boxes: Sequence[BBox]) -> BBox:
        """A menor caixa que contém todas."""
        return cls(
            x0=min(b.x0 for b in boxes),
            y0=min(b.y0 for b in boxes),
            x1=max(b.x1 for b in boxes),
            y1=max(b.y1 for b in boxes),
        )

    @classmethod
    def from_pixels(
        cls, x0: float, y0: float, x1: float, y1: float, *, width_px: float, height_px: float
    ) -> BBox:
        """Normaliza caixas em pixels, como as devolvidas por um motor de OCR."""
        return cls(
            x0=min(max(x0 / width_px, 0.0), 1.0),
            y0=min(max(y0 / height_px, 0.0), 1.0),
            x1=min(max(x1 / width_px, 0.0), 1.0),
            y1=min(max(y1 / height_px, 0.0), 1.0),
        )


class Substrate(StrEnum):
    """De onde veio a camada de texto da página, e se ela pode ser confiada.

    A classificação lê o modo de desenho do texto e a ordem dos objetos no
    PDF, e não depende de limiar. Se a página tem pixels que nenhuma camada
    leu é outro fato, `Page.unread`. Ver o guia de conceitos.
    """

    BORN_DIGITAL = "born_digital"
    """Texto à vista: composto, não reconhecido. Exato e gratuito onde existe."""

    SEARCHABLE_SCAN = "searchable_scan"
    """Texto mais escondido que à vista: camada inserida por OCR, de qualidade desconhecida."""

    IMAGE_ONLY = "image_only"
    """Sem texto embutido. Só um leitor de pixels lê a página."""


class PageDimensions(_Frozen):
    """Dimensões em pontos e em pixels, com o DPI que ligou as duas.

    As três coisas juntas, porque desnormalizar uma caixa exige os pixels e
    reproduzir a renderização exige o DPI.
    """

    width_pt: float = PField(gt=0.0)
    height_pt: float = PField(gt=0.0)
    width_px: int = PField(gt=0)
    height_px: int = PField(gt=0)
    dpi: int = PField(gt=0, le=1200)

    @property
    def paper(self) -> Literal["A4", "Letter", "Ofício"] | None:
        """O formato de papel da folha, em qualquer orientação, ou `None`.

        A4 (210 por 297 mm, ISO 216), Letter (216 por 279 mm, ANSI) e o
        Ofício brasileiro (216 por 330 mm), com 3 mm de folga em cada lado.
        Uma folha fora dos três é um recorte, uma redução ou outro papel.
        """
        short, long = sorted((self.width_pt, self.height_pt))
        short_mm, long_mm = short * 25.4 / 72, long * 25.4 / 72
        for name, (w, h) in _PAPERS.items():
            if abs(short_mm - w) <= 3 and abs(long_mm - h) <= 3:
                return name
        return None


_PAPERS: dict[Literal["A4", "Letter", "Ofício"], tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "Letter": (215.9, 279.4),
    "Ofício": (215.9, 330.2),
}


class Stamp(_Frozen):
    """A tarja que um sistema de processo eletrônico imprime em cada página de uma peça.

    Os campos saem do que o formato (`StampFormat`) nomeia; o que a tarja não
    imprime fica None. A do e-SAJ traz todos, e `protocol` só na peça
    protocolada: o ato liberado nos autos pelo juízo não tem protocolo.
    """

    format: str = PField(description="O nome do `StampFormat` que casou a tarja.")
    code: str = PField(description="O código de conferência: o id da peça juntada.")
    process: str | None = PField(
        default=None, description="O número do processo que a tarja cita, como impresso."
    )
    signer: str | None = PField(
        default=None, description="Quem assinou, como impresso, com os espaços colapsados."
    )
    at: datetime | None = PField(
        default=None,
        description=(
            "Quando a peça foi protocolada ou liberada nos autos: a hora local impressa, sem fuso, "
            "salvo quando o `StampFormat` declara `tz`."
        ),
    )
    protocol: str | None = PField(
        default=None,
        description="O número do protocolo, quando a tarja o imprime.",
    )
    bbox: BBox = PField(description="A menor caixa que contém as linhas da tarja.")
    chunk_ids: tuple[str, ...] = PField(
        min_length=1, description="As linhas da tarja: a da assinatura e a da conferência."
    )


class Folha(_Frozen):
    """A folha dos autos carimbada na página, e a linha de onde veio."""

    value: int = PField(ge=0, description="O número da folha, sem o ponto de milhar.")
    bbox: BBox = PField(description="A caixa da linha do carimbo.")
    chunk_ids: tuple[str, ...] = PField(
        min_length=1, description="A linha do carimbo, uma só na camada de texto."
    )
    in_sequence: bool = PField(
        default=False,
        description=(
            "A folha segue a das outras páginas da execução: a diferença entre a "
            "folha e o índice da página é a mais comum entre as páginas com folha, "
            "e mais de uma página a tem. Um PDF que junta peças de vários "
            "processos, ou trechos separados de um auto, fica com a sequência do "
            "maior trecho. A regra supõe uma página por folha: no auto digitalizado "
            "com o verso de cada folha, a folha sobe uma a cada duas páginas, e "
            "nenhuma segue."
        ),
    )


class Signature(_Frozen):
    """Uma assinatura digital do arquivo, como o PDF a declara.

    O pdfium lê a declaração sem conferir a criptografia: estes campos dizem
    o que o arquivo afirma, não que a assinatura é válida. O signatário fica
    dentro do pacote PKCS#7, que a biblioteca não abre.
    """

    sub_filter: str | None = PField(
        default=None,
        description="O padrão da assinatura: `adbe.pkcs7.detached`, `ETSI.CAdES.detached`.",
    )
    signed_at: datetime | None = PField(
        default=None, description="Quando o arquivo diz ter sido assinado, com o fuso declarado."
    )
    reason: str | None = PField(default=None, description="O motivo declarado, quando há.")
    mdp_permission: int = PField(
        default=0,
        description=(
            "A permissão DocMDP: 0 sem certificação, 1 nenhuma mudança, 2 formulários e "
            "assinaturas, 3 também anotações."
        ),
    )
    covers_file: bool = PField(
        description=(
            "Se o `/ByteRange` chega ao fim do arquivo: nada foi gravado depois desta "
            "assinatura. `False` numa atualização incremental posterior."
        )
    )


class DocumentFacts(_Frozen):
    """O que o arquivo diz de si, lido uma vez, sem renderizar nada.

    `producer` e `creator` são de quem gravou o arquivo por último: uma
    ferramenta que divide um PDF em páginas põe o próprio nome e perde a
    assinatura e a data do original. `saves` e `identifier_changed` dizem se
    o arquivo foi regravado depois de criado.
    """

    producer: str | None = None
    creator: str | None = None
    title: str | None = None
    author: str | None = None
    subject: str | None = None
    keywords: str | None = None
    created_at: datetime | None = PField(
        default=None, description="`/CreationDate`, com o fuso declarado."
    )
    modified_at: datetime | None = PField(
        default=None, description="`/ModDate`, com o fuso declarado."
    )
    pdf_version: str | None = PField(
        default=None,
        description="A versão do PDF, `1.4`, `1.7`; `None` quando o arquivo não a declara.",
    )
    tagged: bool = PField(
        description="Se o PDF tem árvore de estrutura: a ordem de leitura é declarada."
    )
    form: FormKind = PField(description="O tipo de formulário que o arquivo traz.")
    saves: int | None = PField(
        default=None,
        ge=1,
        description=(
            "Quantas vezes o arquivo foi gravado, pelos `startxref`: um da criação, mais um por "
            "atualização incremental. O trailer extra de um arquivo linearizado não conta. "
            "`None` sem o arquivo, como numa imagem."
        ),
    )
    identifier_changed: bool | None = PField(
        default=None,
        description=(
            "Se o `/ID` mutável difere do permanente: o arquivo foi regravado. `None` sem `/ID`."
        ),
    )
    restricted: bool = PField(description="Se o arquivo nega alguma permissão, como copiar texto.")
    page_labels: bool = PField(description="Se o arquivo declara rótulos de página próprios.")
    signatures: tuple[Signature, ...] = PField(
        default=(), description="As assinaturas digitais declaradas."
    )


class Page(_Frozen):
    """Uma página classificada, antes de qualquer leitura cara."""

    doc_id: str
    index: int = PField(ge=0, description="zero-based")
    dimensions: PageDimensions
    substrate: Substrate
    substrate_evidence: dict[str, float] = PField(
        default_factory=dict,
        description=(
            "Números crus do veredito: chars, visible_text, invisible_text, covered_text, "
            "unmapped_text, unread_regions e, quando há raster, native_dpi."
        ),
    )
    stamp: Stamp | None = PField(
        default=None,
        description=(
            "A tarja da camada de texto, num dos formatos de `stamps`; na página "
            "copiada de outro processo, a última desenhada. None sem tarja."
        ),
    )
    folha: Folha | None = PField(
        default=None,
        description=(
            "A folha dos autos carimbada na página, pelo valor de `FOLHA` numa linha de "
            "elemento fixo; no corpo, a mesma forma é citação. None sem carimbo, no "
            "verso e numa execução de uma página só. A forma vem de `folhas=`, e a "
            "regra está em `folhas_of`."
        ),
    )
    unread: tuple[BBox, ...] = PField(
        default=(),
        description=(
            "Caixas dos rasters, e do desenho vetorial, que nenhuma camada de texto leu, "
            "de cima para baixo e da esquerda para a direita. Rasters que se tocam, os "
            "ladrilhos de uma digitalização fatiada, são uma caixa só. Depois da camada de "
            "texto, o leitor seguinte da cascata lê estas regiões, e `Chunk.region` aponta "
            "o índice."
        ),
    )
    hidden_fonts: tuple[str, ...] = PField(
        default=(),
        description=(
            "Os nomes base das fontes do texto desenhado em modo invisível, sem repetição, na "
            "ordem da página. É a assinatura de quem escreveu a camada de uma digitalização: "
            "o Tesseract deixa `GlyphLessFont`, e um montador de tribunal as fontes base do "
            "PDF. Vazio numa página composta."
        ),
    )


class Chunk(_Frozen):
    """Unidade de texto com proveniência. O `id` é determinístico."""

    id: str
    page: int = PField(ge=0, description="zero-based, como em Page.index")
    bbox: BBox
    text: str = PField(description="Texto canônico, com as quebras de linha preservadas.")
    source: str = PField(description="nome do leitor registrado que produziu este texto")
    confidence: float | None = PField(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confiança média do motor. Sinal cru: quem chama aplica o próprio limiar.",
    )

    reading_order: int | None = PField(
        default=None,
        ge=0,
        description="Ordem de leitura dentro da página, atribuída pelo leitor.",
    )
    turn: Turn = PField(
        default=0,
        description=(
            "Graus, no sentido anti-horário, que o leitor girou a página para ler a linha em "
            "pé. A caixa fica no sistema da imagem; sem `layout=`, `reading_order` segue a "
            "leitura. Meça antes de reagrupar as linhas girando as caixas."
        ),
    )
    kind: str | None = PField(
        default=None,
        description=(
            "Tipo da região de onde o texto veio (text, table, paragraph_title...), no "
            "vocabulário do detector de layout do leitor. None quando o leitor não "
            "classifica, que é o caso de um OCR por linha e da camada de texto."
        ),
    )
    line_break_hyphens: tuple[int, ...] = PField(
        default=(),
        description=(
            "Índices em `text` dos hífens que estavam numa quebra de linha do PDF, na "
            "camada de texto. O hífen fica no texto; juntar as metades é de quem lê."
        ),
    )
    region: int | None = PField(
        default=None,
        ge=0,
        description=(
            "Índice em `Page.unread` do raster de onde a linha veio, quando um leitor de "
            "pixels a leu num raster que a camada de texto não leu. None nos outros casos."
        ),
    )
    furniture: bool = PField(
        default=False,
        description=(
            "Elemento fixo da página: a linha repete-se, no mesmo lugar, em outra página lida "
            "que não é cópia desta, "
            "numa sequência a partir da borda da folha ou na vertical da margem. O "
            "cabeçalho, o rodapé e a tarja. A linha fica; quem lê decide se a mostra. "
            "É evidência da própria linha; `kind` é o bloco do detector em que ela caiu, "
            "e para ficar só com o corpo vale `furniture`."
        ),
    )

    @staticmethod
    def make_id(document: str, bbox: BBox, source: str, text: str, *, page: int) -> str:
        """Id determinístico de um chunk, a partir do seu conteúdo e posição.

        O texto e o índice da página entram na chave: dois chunks podem ocupar
        a mesma caixa no mesmo motor, e um documento pode ter duas páginas de
        bytes idênticos. Nenhum pixel entra: o documento, a página e o DPI já
        determinam a renderização, e o id sai igual com ou sem cache e em
        qualquer versão das bibliotecas de imagem.

        Args:
            document: o `doc_id`, com o DPI quando a leitura foi de pixels.
            bbox: a caixa normalizada do chunk.
            source: nome do leitor que o produziu.
            text: o texto do chunk.
            page: índice da página, zero-based.

        Returns:
            Os primeiros `ID_HEX_CHARS` dígitos de um SHA-256.
        """
        raw = f"{document}|{page}|{bbox.key()}|{source}|{text}"
        return hashlib.sha256(raw.encode()).hexdigest()[:ID_HEX_CHARS]

    @staticmethod
    def key_of(page: Page) -> str:
        """O primeiro componente do id de um chunk desta página: documento e DPI."""
        return f"{page.doc_id}:{page.dimensions.dpi}"

    @classmethod
    def make(
        cls,
        page: Page,
        bbox: BBox,
        source: str,
        text: str,
        *,
        confidence: float | None = None,
        reading_order: int | None = None,
        kind: str | None = None,
        line_break_hyphens: tuple[int, ...] = (),
        turn: Turn = 0,
    ) -> Chunk:
        """Um chunk desta página, com o id cunhado sobre o documento, o DPI, a caixa e o texto."""
        return cls(
            id=cls.make_id(cls.key_of(page), bbox, source, text, page=page.index),
            page=page.index,
            bbox=bbox,
            text=text,
            source=source,
            confidence=confidence,
            reading_order=reading_order,
            kind=kind,
            line_break_hyphens=line_break_hyphens,
            turn=turn,
        )


class Region(_Frozen):
    """Uma região da página: rótulo e caixa normalizada. A lista sai na ordem de leitura."""

    label: str
    bbox: BBox


class EntityState(StrEnum):
    """O que a verificação de um campo diz do valor lido."""

    CONFIRMED = "confirmed"
    """A regra tem redundância e confere: o dígito verificador de um CPF, CNPJ ou número CNJ."""

    WELL_FORMED = "well_formed"
    """A forma e a regra passam, sem redundância: um valor bem escrito, uma data que existe."""

    FAILED = "failed"
    """A regra falha. Erro de leitura, ou erro impresso no documento; a página diz qual."""


class Entity(_Frozen):
    """Um valor que uma verificação (`Check`) casou no texto lido, com estado e linha de origem."""

    kind: str = PField(description="O nome do campo, o `name` do `Check` que o casou.")
    value: str = PField(
        description=(
            "O valor lido, com hífens, espaços e formas de largura total tipográficos trocados "
            "pelo ASCII (`fold_lookalikes`) e com os espaços colapsados."
        )
    )
    state: EntityState
    page: int = PField(ge=0, description="zero-based, como em Page.index")
    bbox: BBox = PField(description="A menor caixa que contém as linhas do valor.")
    chunk_ids: tuple[str, ...] = PField(
        min_length=1, description="As linhas que o valor toca: duas quando ele quebra entre linhas."
    )
    span: tuple[int, int] | None = PField(
        default=None,
        description=(
            "Onde o valor está no texto das linhas de `chunk_ids` unidas por quebra de "
            "linha: o começo e o fim, como em `texto[começo:fim]`, antes de colapsar os "
            "espaços. Só com `process(spans=True)`; None por omissão."
        ),
    )
    printed: str | None = PField(
        default=None,
        description=(
            "Num valor `failed`, quem mostra que o erro é do documento. `text_layer`: o valor "
            "veio da camada composta, que não tem leitor a errar. O nome de um leitor: outra "
            "família leu o mesmo valor inválido no mesmo lugar. `None`: o erro pode ser de leitura."
        ),
    )


class OtherReading(_Frozen):
    """Outra leitura do mesmo lugar da folha, ao lado de uma linha do resultado.

    A releitura por outra família e o leitor caro leem de novo a linha que
    falhou. A leitura que confere no mesmo lugar substitui a linha; a que não
    confere fica aqui, ao lado da linha que continuou no resultado. Numa
    digitalização com camada de OCR, a linha da camada que lê outro valor em
    reais também fica aqui, com `check` e `value`, como a linha do leitor caro
    recusada por não trazer um valor que a linha barata trazia. São as linhas
    lidas de dois modos: uma pessoa, ou um terceiro leitor, decide qual é a
    certa.

    Quando a substituição troca o texto, a linha que saiu também fica aqui,
    com `replaced`: a leitura que saiu ao lado da que entrou no mesmo recorte.
    """

    line: str = PField(description="O `Chunk.id` da linha do resultado.")
    reading: Chunk = PField(description="A linha do outro leitor no mesmo lugar da folha.")
    same: bool = PField(
        description=(
            "O outro leitor leu o mesmo valor inválido. Só prova o erro impresso quando "
            "vem de outra família: `confirm=` ou a camada de OCR que outro motor escreveu. "
            "A linha recusada do leitor caro repete o valor e não prova nada; a leitura "
            "que leu outra coisa "
            "não explicou a falha. Sempre `false` numa leitura substituída."
        )
    )
    replaced: bool = PField(
        default=False,
        description=(
            "`reading` estava no resultado e saiu: `line` é a linha que entrou no lugar "
            "dela, da releitura que conferiu ou do leitor caro. `false` numa leitura que "
            "não substituiu a linha."
        ),
    )
    check: str | None = PField(
        default=None,
        description=(
            "Numa linha que não falha: o `Check.name` do valor que o outro leitor lê "
            "diferente, a camada de OCR ou a linha recusada do leitor caro."
        ),
    )
    value: str | None = PField(
        default=None, description="O valor da linha que o outro leitor lê diferente."
    )


class Figure(_Frozen):
    """Uma imagem numa página composta, e as linhas que um leitor de pixels leu dentro dela.

    É o raster de `Page.unread` numa página `BORN_DIGITAL`: a planta, a foto,
    o carimbo, o print de sistema, a tabela colada como imagem. Numa página
    digitalizada a folha inteira é imagem, e ela não é figura.
    """

    ref: str = PField(description="`p<página>:f<índice>`, o nome com que um modelo cita a figura.")
    page: int = PField(ge=0, description="zero-based, como em Page.index")
    index: int = PField(ge=0, description="O índice da imagem em `Page.unread`.")
    bbox: BBox
    chunk_ids: tuple[str, ...] = PField(
        description="As linhas lidas dentro da imagem; vazio numa foto ou assinatura sem texto."
    )


class Record(_Frozen):
    """Um bloco de linhas vizinhas de uma página, agrupado só pela geometria das caixas.

    Sai de `Result.records()`. Cada fileira traz as células da esquerda para
    a direita: uma só numa linha de prosa, várias numa fileira de tabela ou
    de lista em colunas. Não há coluna, cabeçalho nem célula mesclada: isso
    pede a estrutura da tabela, que a biblioteca não monta.
    """

    ref: str = PField(description="`p<página>:b<índice>`, o nome com que um modelo cita o bloco.")
    page: int = PField(ge=0, description="zero-based, como em Page.index")
    index: int = PField(ge=0, description="A posição do bloco na página, de cima para baixo.")
    bbox: BBox
    rows: tuple[tuple[str, ...], ...] = PField(
        min_length=1, description="As fileiras, cada uma com o texto das células."
    )
    chunk_ids: tuple[str, ...] = PField(
        min_length=1, description="As linhas do bloco, fileira a fileira, célula a célula."
    )

    @property
    def tabular(self) -> bool:
        """Se alguma fileira tem mais de uma célula."""
        return any(len(row) > 1 for row in self.rows)

    @property
    def text(self) -> str:
        """As fileiras, uma por linha, com as células separadas por ` | `."""
        return "\n".join(" | ".join(row) for row in self.rows)


class Piece(_Frozen):
    """Páginas seguidas com a mesma tarja: a peça como o sistema de processo a carimbou.

    Sai de `Result.pieces()`, de `Page.stamp`. Páginas seguidas sem tarja
    formam uma peça com `code` None. A biblioteca não diz que peça é, petição,
    decisão ou certidão: isso é de quem lê.
    """

    index: int = PField(ge=0, description="A posição da peça no documento.")
    pages: tuple[int, ...] = PField(min_length=1, description="Os índices das páginas, seguidos.")
    stamp: Stamp | None = PField(description="A tarja da primeira página da peça; None sem tarja.")

    @property
    def code(self) -> str | None:
        """O `Stamp.code` comum às páginas; None sem tarja."""
        return self.stamp.code if self.stamp is not None else None


def _vertical_overlap(a: BBox, b: BBox) -> float:
    """Quanto as duas caixas se sobrepõem na vertical; zero ou menos quando não se tocam."""
    return min(a.y1, b.y1) - max(a.y0, b.y0)


def _spanning(lines: Sequence[Chunk]) -> set[str]:
    """Os ids das linhas que atravessam fileiras: cobrem duas linhas que não se tocam.

    Uma linha cobre outra mais baixa quando passa por mais de metade da altura
    dela. Entre as cobertas, há duas que não se tocam quando a que termina
    primeiro termina antes de a que começa por último começar. É a célula
    mesclada de uma tabela, a tarja vertical na margem, a linha cuja caixa
    atravessa a coluna: nenhuma pertence a uma fileira só.
    """
    out: set[str] = set()
    for line in lines:
        height = line.bbox.y1 - line.bbox.y0
        covered = [
            other.bbox
            for other in lines
            if other is not line
            and other.bbox.y1 - other.bbox.y0 < height
            and _vertical_overlap(line.bbox, other.bbox) > (other.bbox.y1 - other.bbox.y0) / 2
        ]
        if covered and min(b.y1 for b in covered) <= max(b.y0 for b in covered):
            out.add(line.id)
    return out


def _rows_of(lines: Sequence[Chunk]) -> list[list[Chunk]]:
    """As linhas em fileiras: as que se sobrepõem na vertical em mais de metade da menor.

    A linha que atravessa fileiras (`_spanning`) fica numa fileira sozinha, na
    posição dela. Como faixa de uma fileira, ela juntaria todas as linhas ao
    lado e faria da tabela inteira uma fileira só.
    """
    spanning = _spanning(lines)
    rows: list[list[Chunk]] = [[c] for c in lines if c.id in spanning]
    rows.extend(_rows_by_overlap([c for c in lines if c.id not in spanning]))
    rows.sort(key=lambda row: min((c.bbox.y0, c.bbox.x0) for c in row))
    return rows


def _rows_by_overlap(lines: Sequence[Chunk]) -> list[list[Chunk]]:
    """As linhas em fileiras pela sobreposição vertical, da esquerda para a direita."""
    rows: list[list[Chunk]] = []
    for chunk in sorted(lines, key=lambda c: (c.bbox.y0, c.bbox.x0)):
        if rows:
            row = rows[-1]
            span = BBox.envelope([c.bbox for c in row])
            shortest = min(c.bbox.y1 - c.bbox.y0 for c in (*row, chunk))
            if _vertical_overlap(span, chunk.bbox) > shortest / 2:
                row.append(chunk)
                continue
        rows.append([chunk])
    return [sorted(row, key=lambda c: c.bbox.x0) for row in rows]


def reading_order_key(chunk: Chunk) -> tuple[bool, int, float, float]:
    """A ordem de leitura da página: a do leitor, e a linha sem ordem ao fim, de cima para baixo."""
    return (chunk.reading_order is None, chunk.reading_order or 0, chunk.bbox.y0, chunk.bbox.x0)


class Tier(StrEnum):
    """Destino de roteamento de uma página."""

    CHEAP = "cheap"
    STRONG = "strong"


class RoutingDecision(_Frozen):
    """O que a política decidiu para uma página, e com base em quê."""

    page: int = PField(ge=0)
    tier: Tier
    reason: str
    signals: dict[str, int] = PField(
        default_factory=dict,
        description=(
            "Contagem por sinal que disparou nesta página, pelo nome do sinal. É o canal "
            "estruturado de uma política para quem lê o resultado; `reason` é a frase."
        ),
    )
    steps: tuple[str, ...] = PField(
        default=(),
        description=(
            "O que `process` fez com a página, na ordem: quem leu no tier barato e quantas "
            "linhas, o que a releitura por outra família concluiu, o que o leitor caro leu e "
            "o que substituiu. Uma frase por passo, para quem lê o resultado."
        ),
    )
    failures: tuple[str, ...] = PField(
        default=(),
        description=(
            "Cada leitor que falhou nesta página, como `<leitor>: <mensagem>`, na ordem: "
            "o da cascata barata que deu a vez ao seguinte, o da releitura e o caro. "
            "Vazio quando nenhum falhou."
        ),
    )
    incomplete: bool = PField(
        default=False,
        description=(
            "Um leitor falhou e nenhum outro leu no lugar dele: as linhas da página, se "
            "houver, são só parte dela. Falso quando o seguinte da cascata leu, e quando só o "
            "leitor caro falhou e a leitura barata ficou. Numa política que decide antes da "
            "leitura barata, como `all_strong`, a página que o leitor caro recusou não tem leitura "
            "barata, e sem linha nenhuma sai verdadeiro."
        ),
    )
    seconds: dict[str, float] = PField(
        default_factory=dict,
        description=(
            "Os segundos de parede de cada etapa nesta página: `cheap` (a cascata barata e a "
            "detecção de layout), `confirm` (a releitura por outra família) e `strong` (o "
            "leitor caro). Só as etapas que tocaram a página; uma leitura do cache conta o "
            "tempo que levou."
        ),
    )


class Budget(_Frozen):
    """Teto opcional do leitor caro, em páginas e em segundos.

    Com as duas formas em páginas, vale a mais restritiva. `max_seconds` é o
    tempo de parede da execução a partir do qual o tier caro não começa
    página nova. A releitura por outra família termina sempre. A página
    escalada que o teto alcançou fica com a leitura barata, feita então se a
    política a tinha dispensado; o motivo vai em `RoutingDecision.steps`. Tokens e dólares não
    têm teto: são relatados em `Result.spent`.
    """

    max_strong_pages: int | None = PField(default=None, ge=0)
    max_strong_fraction: float | None = PField(default=None, ge=0.0, le=1.0)
    max_seconds: float | None = PField(default=None, gt=0.0)

    def page_allowance(self, total_pages: int) -> int | None:
        """Quantas páginas o orçamento permite encaminhar, dado o total do documento.

        Devolve `None` quando nenhum limite de página foi declarado.
        """
        caps: list[int] = []
        if self.max_strong_pages is not None:
            caps.append(self.max_strong_pages)
        if self.max_strong_fraction is not None:
            # Para cima: uma fração que não é zero deixa escalar ao menos uma
            # página num documento curto.
            caps.append(math.ceil(total_pages * self.max_strong_fraction))
        return min(caps) if caps else None


class Spent(_Frozen):
    """O que uma execução gastou: páginas por etapa, cache, segundos e o que um `Metered` contou.

    `pages_cheap` conta as páginas lidas no tier barato, o que inclui as
    escaladas quando a política precisa da leitura barata; `regions_cheap`
    conta as páginas em que o leitor seguinte da cascata leu, como região, os
    rasters que a camada de texto não leu; `regions_strong` conta as páginas
    em que o leitor caro leu só as regiões das linhas que falharam;
    `lines_strong_rejected` conta as linhas do leitor caro que não entraram
    no lugar das baratas, por perderem um valor que conferia ou por não
    explicarem o que falhou. Os `*_cached` contam o que veio do cache em
    cada etapa; os `seconds_*` são o tempo de parede de cada etapa, com a
    detecção de layout das páginas que ela renderizou. `calls`, `tokens_in`,
    `tokens_out` e `usd` são o que um leitor `Metered` contou nesta
    execução, e ficam `None` sem um. Tudo relatado, nada limitado.
    """

    pages_total: int
    pages_cheap: int
    pages_strong: int = 0
    pages_cheap_cached: int = 0
    pages_cheap_failed: int = 0
    regions_cheap: int = 0
    regions_strong: int = 0
    lines_strong_rejected: int = 0
    pages_strong_cached: int = 0
    pages_strong_failed: int = 0
    pages_confirmed: int = 0
    pages_confirmed_same: int = 0
    pages_confirmed_fixed: int = 0
    pages_confirm_cached: int = 0
    pages_layout_cached: int = 0
    seconds_cheap: float = 0.0
    seconds_confirm: float = 0.0
    seconds_strong: float = 0.0
    seconds: float
    calls: float | None = None
    tokens_in: float | None = None
    tokens_out: float | None = None
    usd: float | None = None


class Run(_Frozen):
    """Com que leitores, em que versão e com que argumentos um `Result` foi produzido.

    É o que basta para refazer a leitura, e para saber, meses depois, que
    pesos, motor e dispositivo leram cada linha: `Chunk.source` é chave de
    `versions`. Os nomes são os dos leitores; a configuração de cada um
    está na versão dele.
    """

    started_at: datetime = PField(description="O início da execução, em UTC.")
    policy: str = PField(description="O `name` da política de triagem.")
    budget: Budget
    cheap: tuple[str, ...] = PField(description="Os leitores da cascata barata, na ordem.")
    confirm: str | None = PField(description="O leitor da releitura por outra família.")
    strong: str | None = PField(description="O leitor caro.")
    reread: Reread
    trust_layer: TrustLayer
    dpi: int | None = PField(
        description=(
            "O DPI pedido; `None` deixa cada página escolher. O de cada página está em "
            "`Page.dimensions`."
        )
    )
    entities: tuple[str, ...] = PField(
        description="Os nomes das verificações de `Result.entities`, na ordem."
    )
    stamps: tuple[str, ...] = PField(
        default=(), description="Os nomes dos formatos de tarja procurados, na ordem."
    )
    folhas: tuple[str, ...] = PField(
        default=(), description="Os nomes das formas de folha procuradas, na ordem."
    )
    spans: bool = PField(default=False, description="Se `Entity.span` foi pedido.")
    min_raster_fraction: float = PField(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "A fração da página abaixo da qual um raster não lido de uma página nato-digital "
            "não foi ao leitor de pixels; `0.0` leu todos."
        ),
    )
    versions: dict[str, str] = PField(
        description=(
            "O `output_version` de cada leitor que leu alguma linha do resultado, pelo "
            "nome dele, e do detector de layout em `layout`. É a versão que entra na "
            "chave do cache: pesos, motor, dispositivo, idioma, prompt."
        )
    )


_ELLIPSES = ("[...]", "[\u2026]", "(...)", "(\u2026)", "...", "\u2026")
"""As marcas de reticências que um modelo escreve ao resumir uma citação."""


def _split_ellipses(value: str) -> list[str]:
    """Os pedaços de uma citação, separados nas reticências, sem os vazios."""
    pieces = [value]
    for mark in _ELLIPSES:
        pieces = [part for piece in pieces for part in piece.split(mark)]
    return [p.strip() for p in pieces if p.strip()]


def _letters_and_digits(text: str) -> str:
    """Só as letras e os dígitos, com os parecidos tipográficos dobrados."""
    # Import local: `policies` importa este módulo.
    from docaudit.policies import fold_lookalikes

    return "".join(ch for ch in fold_lookalikes(text) if ch.isalnum())


class Result(_Frozen):
    """Saída de `process`: o que foi lido, como foi roteado e o que custou.

    É um modelo Pydantic: `model_dump_json()` serializa tudo e
    `Result.model_json_schema()` descreve o formato. Os nove métodos abaixo
    dão as outras formas de uso: as linhas por página, os leitores por
    página, a contagem por verificação, as referências curtas, a citação
    conferida, as figuras, os blocos, as peças e o texto em Markdown.
    """

    doc_id: str
    pages: tuple[Page, ...] = PField(
        description="As páginas processadas, com substrato e evidência, na ordem do documento."
    )
    chunks: tuple[Chunk, ...]
    decisions: tuple[RoutingDecision, ...]
    entities: tuple[Entity, ...] = PField(
        default=(),
        description=(
            "Os valores com forma e regra achados nas linhas, com estado e linha de origem, "
            "na ordem das páginas."
        ),
    )
    others: tuple[OtherReading, ...] = PField(
        default=(),
        description=(
            "As leituras de outro leitor no lugar das linhas que ainda falham, na ordem "
            "em que foram feitas."
        ),
    )
    spent: Spent
    run: Run | None = PField(
        default=None,
        description=(
            "Os leitores, as versões e os argumentos da execução. `process` sempre o "
            "preenche; `None` num JSON sem o campo."
        ),
    )
    document: DocumentFacts | None = PField(
        default=None,
        description=(
            "O que o arquivo diz de si: produtor, datas, versão, assinaturas, gravações. "
            "`process` sempre o preenche; `None` num JSON sem o campo."
        ),
    )
    library_version: str

    def by_page(self) -> dict[int, list[Chunk]]:
        """Os chunks de cada página, na ordem de leitura.

        Uma linha sem ordem, que é a linha barata que o leitor caro não
        substituiu, vai ao fim, de cima para baixo. É a única ordem que a
        biblioteca usa para apresentar o texto.
        """
        grouped: dict[int, list[Chunk]] = {p.index: [] for p in self.pages}
        for chunk in self.chunks:
            grouped.setdefault(chunk.page, []).append(chunk)
        return {index: sorted(chunks, key=reading_order_key) for index, chunks in grouped.items()}

    def read_by(self) -> dict[int, tuple[str, ...]]:
        """Os leitores que deram linhas a cada página, sem repetição, na ordem em que aparecem.

        É o fato que `Page.substrate` não diz: a folha digitalizada sob uma tarja
        de texto é `born_digital`, e o corpo dela vem dos pixels. Vazio na página
        sem linha.
        """
        return {
            index: tuple(dict.fromkeys(c.source for c in chunks))
            for index, chunks in self.by_page().items()
        }

    def verification(self) -> dict[int, dict[str, dict[str, int]]]:
        """Por página e por verificação, quantos valores em cada `EntityState`.

        A chave `printed` conta, entre os que falham, os que outra família leu
        igual: o erro está no documento, e não na leitura. A página sem valor não
        entra.
        """
        out: dict[int, dict[str, dict[str, int]]] = {}
        for entity in self.entities:
            counts = out.setdefault(entity.page, {}).setdefault(entity.kind, {})
            counts[entity.state.value] = counts.get(entity.state.value, 0) + 1
            if entity.state is EntityState.FAILED and entity.printed is not None:
                counts["printed"] = counts.get("printed", 0) + 1
        return out

    def refs(self) -> dict[str, Chunk]:
        """Uma referência curta por linha, `p<página>:<posição>`, na ordem de leitura.

        É o nome pelo qual um modelo ou uma pessoa cita a linha: curto o
        bastante para caber numa resposta sem erro, e derivado só da ordem
        deste resultado. `Chunk.id` continua sendo a identidade estável da
        linha entre execuções; a referência vale dentro de um resultado.
        """
        return dict(self._refs)

    @functools.cached_property
    def _refs(self) -> dict[str, Chunk]:
        """A tabela de `refs`, montada uma vez: o resultado não muda depois de pronto."""
        return {
            f"p{index}:{n}": chunk
            for index, chunks in self.by_page().items()
            for n, chunk in enumerate(chunks)
        }

    def cited(
        self, refs: str | Sequence[str], value: str, *, entity: str | None = None
    ) -> list[Chunk]:
        """As linhas citadas, se `value` está no texto delas; vazio se a citação não confere.

        Confere sem modelo. Só as letras e os dígitos contam: espaço,
        pontuação, aspas e hífen tipográfico não, porque é neles que a cópia
        de um modelo e a leitura de um OCR diferem sem mudar o que está
        escrito. O valor tem de estar no texto das linhas `refs`, unidas na
        ordem citada. Um valor que quebra entre duas linhas, como `R$` numa e
        o número na seguinte, cita as duas.

        Uma citação longa pode vir resumida com reticências (`...`, `…`,
        `[...]`). Cada pedaço tem de estar no texto, inteiro, e na ordem em
        que foi citado: a ordem carrega o sentido (quem cedeu a quem), e
        pedaços certos fora de ordem não conferem. `entity`, quando dado, é
        o valor que a citação tem de conter (um nome, um id): um trecho que
        fala do fato sem falar da entidade não prova o fato dela.

        Uma referência que não existe neste resultado, um valor vazio ou um
        pedaço vazio não conferem. Confira contra o resultado cujo texto o
        modelo leu: outra leitura pode numerar as linhas de outro jeito.
        """
        names = [refs] if isinstance(refs, str) else list(refs)
        known = self._refs
        if any(name not in known for name in names):
            return []
        lines = [known[name] for name in names]
        pieces = [_letters_and_digits(p) for p in _split_ellipses(value)]
        if not pieces or not all(pieces):
            return []
        flat = _letters_and_digits("".join(c.text for c in lines))
        at = 0
        for piece in pieces:
            found = flat.find(piece, at)
            if found < 0:
                return []
            at = found + len(piece)
        if entity is not None:
            wanted = _letters_and_digits(entity)
            if not wanted or wanted not in "".join(pieces):
                return []
        return lines

    def figures(self) -> list[Figure]:
        """As imagens das páginas compostas, com as linhas lidas em cada uma, na ordem das páginas.

        Sai do que o resultado já tem: as caixas de `Page.unread` e o
        `Chunk.region` de cada linha. Para mostrar uma figura a um modelo ou a
        uma pessoa, `Document.crop(figure.page, figure.bbox)` a recorta.
        """
        by_region: dict[tuple[int, int], list[str]] = {}
        for chunk in self.chunks:
            if chunk.region is not None:
                by_region.setdefault((chunk.page, chunk.region), []).append(chunk.id)
        return [
            Figure(
                ref=f"p{page.index}:f{index}",
                page=page.index,
                index=index,
                bbox=box,
                chunk_ids=tuple(by_region.get((page.index, index), ())),
            )
            for page in self.pages
            if page.substrate is Substrate.BORN_DIGITAL
            for index, box in enumerate(page.unread)
        ]

    def records(self, *, furniture: bool = True, gap: float = 1.0) -> list[Record]:
        """As linhas de cada página em fileiras e blocos, só pela geometria das caixas.

        Duas linhas que se sobrepõem na vertical em mais de metade da menor
        estão na mesma fileira, da esquerda para a direita: as células de
        uma tabela, ou as colunas de uma lista. A linha que cobre duas linhas
        que não se tocam, como uma célula mesclada ou uma tarja vertical,
        fica numa fileira sozinha. Fileiras seguidas cujo vão
        vertical não passa de `gap` vezes a altura mediana das linhas da
        página estão no mesmo bloco: um parágrafo, ou uma tabela inteira.
        `gap` não está calibrado: é a razão entre o vão que separa dois
        parágrafos e a altura de uma linha, e muda com o entrelinhamento do
        documento. Nenhum modelo roda aqui. Numa página em duas colunas sem
        detector de layout, as linhas lado a lado saem como células de uma
        fileira; `process(layout=)` dá a ordem por bloco nesse caso. A linha
        lida de lado sai sozinha no bloco dela. Com `furniture=False`, as
        linhas de elemento fixo ficam de fora.
        """
        out: list[Record] = []
        for page, chunks in self.by_page().items():
            lines = [c for c in chunks if furniture or not c.furniture]
            upright = [c for c in lines if c.turn == 0]
            heights = sorted(c.bbox.y1 - c.bbox.y0 for c in upright)
            median = heights[len(heights) // 2] if heights else 0.0
            blocks: list[list[list[Chunk]]] = []
            bottom = 0.0
            for row in _rows_of(upright):
                span = BBox.envelope([c.bbox for c in row])
                if blocks and span.y0 - bottom <= gap * median:
                    blocks[-1].append(row)
                else:
                    blocks.append([row])
                bottom = span.y1
            blocks.extend([[c]] for c in lines if c.turn != 0)
            for index, block in enumerate(blocks):
                cells = [c for row in block for c in row]
                out.append(
                    Record(
                        ref=f"p{page}:b{index}",
                        page=page,
                        index=index,
                        bbox=BBox.envelope([c.bbox for c in cells]),
                        rows=tuple(tuple(c.text for c in row) for row in block),
                        chunk_ids=tuple(c.id for c in cells),
                    )
                )
        return out

    def pieces(self) -> list[Piece]:
        """As páginas em peças, pelo código da tarja, na ordem do documento.

        Uma peça é uma sequência de páginas com o mesmo `Stamp.code`; as
        páginas seguidas sem tarja formam uma peça sem código. É um
        agrupamento do que a tarja já diz, sem classificar a peça: serve
        para pedir o texto de uma peça em vez do documento inteiro.
        """

        def code_of(page: Page) -> str | None:
            return page.stamp.code if page.stamp is not None else None

        return [
            Piece(index=index, pages=tuple(p.index for p in run), stamp=run[0].stamp)
            for index, (_, group) in enumerate(itertools.groupby(self.pages, key=code_of))
            for run in (list(group),)
        ]

    def to_markdown(self, *, furniture: bool = True, annotated: bool = False) -> str:
        """O texto lido, uma linha por chunk, com um cabeçalho por página.

        O cabeçalho traz o índice da página, zero-based, e quem a leu. Serve
        para busca; a proveniência fina fica em `chunks`. Com `annotated`,
        o cabeçalho traz também o documento e a folha da página
        (`Page.stamp`, `Page.folha`), cada linha começa pela referência de
        `refs()`, e cada página termina com a decisão da cascata, as
        entidades achadas nela com estado e referência, as linhas com mais
        de um valor do mesmo tipo, os blocos do detector de layout quando há
        um, e as figuras. É a forma de entregar a leitura a um modelo; o que
        cada parte lhe diz, e como a citação é conferida, está em
        `docs/agent.md`.
        """
        parts: list[str] = []
        if annotated and self.document is not None:
            facts = self.document
            head = [f"PDF {facts.pdf_version}"] if facts.pdf_version else []
            if facts.producer:
                head.append(f"gravado por {facts.producer}")
            if facts.signatures:
                head.append(f"{len(facts.signatures)} assinatura(s)")
            if facts.saves and facts.saves > 1:
                head.append(f"{facts.saves} gravações")
            if head:
                parts.append(f"<!-- documento · {' · '.join(head)} -->")
        reasons = {d.page: d.reason for d in self.decisions} if annotated else {}
        found: dict[int, list[Entity]] = {}
        for entity in self.entities if annotated else ():
            found.setdefault(entity.page, []).append(entity)
        # A linha de lista: mais de um valor do mesmo tipo na mesma linha, como
        # uma fileira de tabela com dois CNPJ ou dois valores. Categórico, sem
        # limiar. Um modelo lê uma linha de lista de outro jeito que uma frase.
        per_line: dict[str, dict[str, int]] = {}
        for entity in self.entities if annotated else ():
            for cid in entity.chunk_ids:
                kinds = per_line.setdefault(cid, {})
                kinds[entity.kind] = kinds.get(entity.kind, 0) + 1
        lists = {cid for cid, kinds in per_line.items() if any(n > 1 for n in kinds.values())}
        figures: dict[int, list[Figure]] = {}
        for figure in self.figures() if annotated else ():
            figures.setdefault(figure.page, []).append(figure)
        pages = {p.index: p for p in self.pages}
        for index, chunks in self.by_page().items():
            refs = {c.id: f"p{index}:{n}" for n, c in enumerate(chunks)}
            sources = ", ".join(sorted({c.source for c in chunks})) or "nada lido"
            stamp = pages[index].stamp if annotated else None
            folha = pages[index].folha if annotated else None
            header = f"<!-- página {index} · {sources}"
            if stamp is not None:
                header += (
                    f" · documento {stamp.code} ({', '.join(refs[c] for c in stamp.chunk_ids)})"
                )
            if folha is not None:
                header += f" · fls. {folha.value} ({', '.join(refs[c] for c in folha.chunk_ids)})"
            parts.append(header + " -->")
            parts.extend(
                f"[{refs[c.id]}] {c.text}" if annotated else c.text
                for c in chunks
                if furniture or not c.furniture
            )
            if annotated:
                parts.append(f"<!-- decisão: {reasons[index]} -->")
                if listed := [refs[c.id] for c in chunks if c.id in lists]:
                    parts.append(f"- linhas de lista: {', '.join(listed)}")
                blocks: dict[str, list[str]] = {}
                for c in chunks:
                    if c.kind:
                        blocks.setdefault(c.kind, []).append(refs[c.id])
                if blocks:
                    parts.append(
                        "- blocos: "
                        + "; ".join(f"{kind}: {', '.join(r)}" for kind, r in blocks.items())
                    )
                parts.extend(
                    f"- {e.kind}: {e.value} · {e.state}"
                    + (f" (impresso assim: {e.printed})" if e.printed else "")
                    + f" · {', '.join(refs[c] for c in e.chunk_ids)}"
                    for e in found.get(index, ())
                )
                # A figura com texto lido entra uma a uma; as sem texto, numa
                # linha só: uma digitalização fatiada em ladrilhos dá milhares
                # de imagens numa página, e cada uma seria uma linha a pagar.
                blank = 0
                hidden = {c.id for c in chunks if c.furniture and not furniture}
                for f in figures.get(index, ()):
                    if not f.chunk_ids:
                        blank += 1
                        continue
                    if hidden.issuperset(f.chunk_ids):
                        continue  # o selo do cabeçalho: as linhas dele saíram do texto
                    read = ", ".join(refs[c] for c in f.chunk_ids)
                    parts.append(
                        f"- figura {f.ref}: {f.bbox.area:.0%} da página · "
                        f"{len(f.chunk_ids)} linha(s) lida(s): {read}"
                    )
                if blank:
                    parts.append(f"- {blank} imagem(ns) sem texto lido")
            parts.append("")
        return "\n".join(parts)


# ── Contratos de extensão ────────────────────────────────────────────────────
# Protocols, não ABCs: um backend de terceiro satisfaz o contrato sem herdar
# nada nem importar além destes tipos, e o pyright verifica a conformidade
# estrutural. O comportamento, que o Protocol não garante, é coberto pelas
# suítes de contrato.


@runtime_checkable
class Reader(Protocol):
    """Lê uma página e devolve chunks. O mesmo contrato serve aos dois tiers.

    `process` percorre a cascata na ordem que o chamador declarou, e a
    primeira leitura não vazia vence. Um leitor caro também é um `Reader`: a
    diferença entre os tiers é quem decide chamá-lo, não a forma dele.
    """

    # Propriedades só de leitura: `process()` nunca as escreve, e assim tanto
    # um atributo de classe quanto um `@property` satisfazem o contrato.
    @property
    def name(self) -> str: ...

    @property
    def external(self) -> bool:
        """True se envia dados para fora da máquina.

        `process()` recusa um leitor assim sem `allow_external=True`.
        """
        ...

    @property
    def output_version(self) -> str:
        """Versão do que este leitor produz: pesos, idioma, prompt e formato de saída.

        Entra na chave do cache. Tudo o que muda a leitura sem mudar o nome do
        leitor tem de estar aqui, senão o cache serve a leitura antiga.
        """
        ...

    def read(self, view: PageView) -> Sequence[Chunk]: ...


@runtime_checkable
class Metered(Protocol):
    """Um leitor que conta o que gasta a cada chamada.

    `usage` acumula ao longo da vida do leitor: `calls`, `tokens_in`,
    `tokens_out` e, quando o leitor conhece o preço, `usd`. `process()` mede a
    diferença entre o início e o fim de uma execução e a soma em
    `Result.spent`, de modo que uma leitura servida pelo cache não conta.
    """

    @property
    def usage(self) -> Mapping[str, float]: ...


@runtime_checkable
class Layout(Protocol):
    """Detecta as regiões de uma página renderizada, na ordem de leitura.

    `process(..., layout=...)` usa o detector para pôr as linhas de qualquer
    leitor na ordem dos blocos da página: numa folha em duas colunas, a
    coluna da esquerda inteira antes da direita. `PPDocLayout` o implementa.
    """

    @property
    def output_version(self) -> str:
        """Pesos e parâmetros do detector; entra na chave do cache."""
        ...

    def detect(self, image: bytes) -> Sequence[Region]:
        """As regiões de uma página em PNG, na ordem de leitura."""
        ...


@runtime_checkable
class TriagePolicy(Protocol):
    """Decide o tier de cada página dentro de um orçamento.

    Recebe as páginas já classificadas e o orçamento. `Page.substrate_evidence`
    carrega os números crus de cada uma. O teto de `Budget`, quando há, vale
    para qualquer política: `process()` o aplica sobre as decisões.
    """

    @property
    def name(self) -> str: ...

    @property
    def signals(self) -> Sequence[Signal]:
        """Os sinais da política, na ordem de prioridade; vazio numa política sem sinal.

        `Document.doubts` lista as linhas apontadas pelos que são `LineSignal`.
        """
        ...

    @property
    def checks(self) -> Sequence[FailsCheck]:
        """As verificações entre os sinais, que apontam a linha que falhou.

        São elas que a releitura por outra família e a leitura cara por região
        usam. Uma política sem verificação devolve a sequência vazia.
        """
        ...

    @property
    def needs_reads(self) -> bool:
        """True se a decisão depende do que a cascata barata leu.

        Com True, `process()` lê toda página no tier barato antes de decidir e
        passa as leituras em `reads`; uma página escalada é lida duas vezes. Com
        False, a decisão vem antes de qualquer leitura, e a página encaminhada
        não paga o tier barato. Há duas exceções. Sem leitor caro
        (`strong=None`), toda página é lida no tier barato. E a página que o
        teto `Budget.max_seconds` tirou do leitor caro é lida no tier barato.
        """
        ...

    def decide(
        self,
        pages: Sequence[Page],
        budget: Budget,
        reads: Mapping[int, Sequence[Chunk]] | None = None,
    ) -> Sequence[RoutingDecision]: ...
