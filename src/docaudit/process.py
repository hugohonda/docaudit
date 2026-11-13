# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A função de alto nível: `process`.

Abre o documento uma vez, classifica o substrato de cada página, deixa a
política decidir e lê cada página no tier que ela recebeu. Cada etapa é
substituível por argumento, e esta assinatura é o contrato que menos deve
mudar.

Uma política que decide só pelo substrato decide antes de qualquer leitura, e
a página encaminhada não paga o tier barato, salvo sem leitor caro e salvo a
que o teto `max_seconds` tirou do leitor caro. Uma que precisa da leitura
barata (`needs_reads`) recebe a de todas as páginas, e uma página escalada é
lida nos dois tiers. A leitura cara substitui a barata onde leu; a linha
barata fora das caixas da leitura cara fica. Com `reread="region"`, o
leitor caro recebe um recorte por linha que falhou uma verificação. O teto
de `Budget` vale para qualquer política.
"""

from __future__ import annotations

import re
import time
import warnings
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, cast
from zoneinfo import ZoneInfo

from docaudit import pdf as _pdf
from docaudit.backends.textlayer import TextLayerReader
from docaudit.cache import call_key
from docaudit.pdf import PageView, merge_touching
from docaudit.policies import (
    AMOUNT_BRL,
    DEFAULT_ENTITIES,
    DEFAULT_STAMPS,
    FOLHA,
    FOLHA_FORMATS,
    STAMP_FORMATS,
    GarbledText,
    StampFormat,
    _machine_chunks,  # pyright: ignore[reportPrivateUsage] - a mesma regra de texto composto dos sinais
    entities_of,
    fold_lookalikes,
    garbled_runs,
    get_policy,
    touched_lines,
)
from docaudit.registry import get_backend
from docaudit.types import (
    BBox,
    Budget,
    Chunk,
    DocumentFacts,
    Entity,
    EntityState,
    ExternalBackendError,
    Folha,
    Layout,
    Metered,
    OtherReading,
    Page,
    Reader,
    Region,
    Reread,
    Result,
    RoutingDecision,
    Run,
    Spent,
    Stamp,
    Substrate,
    Tier,
    TriagePolicy,
    TrustLayer,
    Turn,
    reading_order_key,
)

if TYPE_CHECKING:
    from collections.abc import Container, Mapping, Sequence

    import pypdfium2 as pdfium

    from docaudit.cache import ModelCallCache
    from docaudit.policies import Check, FailsCheck

__all__ = [
    "DEFAULT_CASCADE",
    "RASTER_MARGIN",
    "Reread",
    "TrustLayer",
    "folhas_of",
    "mark_furniture",
    "process",
    "read_region",
    "refuse_external",
    "resolve",
    "run_pipeline",
    "stamps_of",
]

DEFAULT_CASCADE: tuple[str, ...] = ("text_layer", "ppocr")
"""A camada de texto onde houver, o PP-OCR no resto.

Numa `SEARCHABLE_SCAN`, com o padrão `trust_layer="visible"`, o PP-OCR lê
os pixels, e a camada fica como outra família.

PP-OCR, e não Tesseract, porque lê melhor páginas escaneadas, a um custo
maior. O Tesseract é registrado como a alternativa
rápida.
"""

_CACHED = " (do cache)"

RASTER_MARGIN = 0.15
"""A folga, em fração da folha, em volta do recorte de um raster.

Um recorte justo corta o texto na borda, e o detector de linhas parte a linha
ali. É um ponto de partida, não um ótimo calibrado.
"""


def resolve[T](spec: T | str, protocol: type[T], lookup: Callable[[str], type]) -> T:
    """Instancia um backend ou política dado por nome, ou devolve o objeto como veio.

    O `isinstance` contra o Protocol faz um entry point mal registrado falhar
    aqui, nomeando o contrato, em vez de virar um `AttributeError` no meio da
    leitura de uma página. Vale também para o objeto passado direto: a classe
    no lugar da instância, `strong=PPOCR`, falharia só depois do tier barato.
    """
    instance = lookup(spec)() if isinstance(spec, str) else spec
    if isinstance(instance, type) or not isinstance(instance, protocol):
        hint = "; passe uma instância, não a classe" if isinstance(instance, type) else ""
        raise TypeError(f"{spec!r} não satisfaz o contrato {protocol.__name__}{hint}")
    return instance


def refuse_external(backends: Sequence[Reader | None]) -> None:
    """Recusa qualquer backend que declare sair da máquina.

    Antes de abrir o documento, não no meio do laço: um erro que só aparece na
    página 300 é pior que inútil. A checagem é sobre a declaração `external`,
    não sobre o conteúdo da página. A biblioteca não tem como saber o que é
    sigiloso, mas tem como saber o que sai da máquina.
    """
    external = [b.name for b in backends if b is not None and b.external]
    if external:
        raise ExternalBackendError(
            f"{', '.join(external)} envia(m) dados para fora da máquina. "
            "Passe allow_external=True se é isso mesmo que você quer."
        )


def _named[T](
    given: Sequence[T | str] | None, default: Sequence[T], known: Mapping[str, T]
) -> tuple[T, ...]:
    """Os formatos pedidos, com cada nome trocado pelo formato de `known`; `None` é `default`."""
    if given is None:
        return tuple(default)
    out: list[T] = []
    for item in given:
        if isinstance(item, str):
            if item not in known:
                raise ValueError(f"{item!r} desconhecido; aceitos: {sorted(known)}")
            out.append(known[item])
        else:
            out.append(item)
    return tuple(out)


def _entity_checks(policy: TriagePolicy, entities: Sequence[Check] | None) -> list[Check]:
    """As verificações de `Result.entities`: as pedidas, ou as da política e depois as padrão."""
    if entities is not None:
        return list(entities)
    chosen = {c.check.name: c.check for c in policy.checks}
    for check in DEFAULT_ENTITIES:
        chosen.setdefault(check.name, check)
    return list(chosen.values())


def _usage_of(readers: Sequence[Reader | None]) -> dict[str, float]:
    """Soma dos contadores dos leitores que contam o que gastam.

    É lida antes e depois da execução: a diferença é o gasto desta chamada, e
    um leitor reaproveitado entre chamadas não traz o gasto da anterior. Um
    leitor passado em dois papéis, como `strong` e `confirm`, conta uma vez.
    """
    total: dict[str, float] = {}
    for reader in {id(r): r for r in readers if r is not None}.values():
        if isinstance(reader, Metered):
            for key, value in reader.usage.items():
                total[key] = total.get(key, 0.0) + float(value)
    return total


def _warn_failure(reader: Reader, page: Page, exc: RuntimeError) -> str:
    """Avisa a falha de um leitor numa página, e devolve a nota de `RoutingDecision.failures`."""
    warnings.warn(
        f"o leitor {reader.name} falhou na página {page.index}: {exc}",
        RuntimeWarning,
        stacklevel=3,
    )
    return f"{reader.name}: {exc}"


# ── Geometria ────────────────────────────────────────────────────────────────


def _distance(box: BBox, cx: float, cy: float) -> float:
    """Distância ao quadrado do ponto à caixa; zero dentro dela."""
    dx = max(box.x0 - cx, 0.0, cx - box.x1)
    dy = max(box.y0 - cy, 0.0, cy - box.y1)
    return dx * dx + dy * dy


def _centre(box: BBox) -> tuple[float, float]:
    return (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2


def _covering(box: BBox, read: Sequence[Chunk]) -> list[Chunk]:
    """O que já foi lido e contém o centro de `box`.

    O centro, e não a sobreposição: a tarja do e-SAJ corre a margem inteira
    na vertical, e toda linha do corpo que chega à margem a tocaria.
    """
    cx, cy = _centre(box)
    return [c for c in read if _distance(c.bbox, cx, cy) == 0.0]


def _already_read(box: BBox, read: Sequence[Chunk]) -> bool:
    """True se o centro de `box` cai dentro da caixa de algo já lido."""
    return bool(_covering(box, read))


def _replaced(line: Chunk, reading: Chunk) -> list[OtherReading]:
    """A leitura que saiu do resultado, ao lado da linha que entrou no lugar dela.

    Só quando o texto muda: a linha relida com o mesmo texto não ensina nada.
    """
    if line.text == reading.text:
        return []
    return [OtherReading(line=line.id, reading=reading, same=False, replaced=True)]


def _within(chunks: Sequence[Chunk], box: BBox) -> list[Chunk]:
    """Os trechos cujo centro cai em `box`, com a caixa presa a ela.

    O que o leitor viu em volta de `box` é contexto, não região lida: a linha
    de fora fica de fora, e a caixa de um leitor que devolve um bloco inteiro
    não pode engolir a linha vizinha.
    """
    out: list[Chunk] = []
    for chunk in chunks:
        if _distance(box, *_centre(chunk.bbox)) > 0.0:
            continue
        clipped = BBox(
            x0=max(chunk.bbox.x0, box.x0),
            y0=max(chunk.bbox.y0, box.y0),
            x1=min(chunk.bbox.x1, box.x1),
            y1=min(chunk.bbox.y1, box.y1),
        )
        out.append(chunk if clipped == chunk.bbox else chunk.model_copy(update={"bbox": clipped}))
    return out


# ── Leituras, servidas pelo cache ────────────────────────────────────────────


def _read_cached(
    view: PageView, reader: Reader, cache: ModelCallCache | None
) -> tuple[Sequence[Chunk], bool, bool]:
    """Leitura de uma página, ou de uma região dela, servida pelo cache quando possível.

    Devolve os chunks, se vieram do cache, e se o leitor pediu os pixels. O
    segundo valor alimenta o `Result.spent`, para que uma execução servida
    pelo cache não reporte o mesmo gasto de uma que chamou o leitor. O
    terceiro diz à cascata se a leitura já cobriu os rasters da página; vai
    no cache junto com os chunks, e uma entrada sem ele é relida.
    """
    page = view.page
    region = view.box.key() if view.box is not None else ""
    key = call_key(
        page.doc_id,
        page.index,
        page.dimensions.dpi,
        reader.name,
        reader.output_version,
        region=f"{region}@{view.turn}" if view.turn else region,
    )
    if cache is not None:
        hit = cache.get(key)
        if hit is not None and "rendered" in hit:
            chunks = [Chunk.model_validate(c) for c in cast("list[object]", hit["chunks"])]
            return chunks, True, bool(hit["rendered"])
    produced = list(reader.read(view))
    rendered = view.rendered
    if cache is not None:
        cache.put(
            key,
            reader.name,
            reader.output_version,
            {"chunks": [c.model_dump(mode="json") for c in produced], "rendered": rendered},
        )
    return produced, False, rendered


def _regions_cached(
    view: PageView, layout: Layout, cache: ModelCallCache | None
) -> tuple[list[Region], bool]:
    """As regiões da página pelo detector, servidas pelo cache quando possível."""
    page = view.page
    key = call_key(page.doc_id, page.index, page.dimensions.dpi, "layout", layout.output_version)
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return [Region.model_validate(r) for r in cast("list[object]", hit["regions"])], True
    regions = list(layout.detect(view.image(grayscale=False)))
    if cache is not None:
        cache.put(
            key, "layout", layout.output_version, {"regions": [r.model_dump() for r in regions]}
        )
    return regions, False


def read_region(
    view: PageView,
    box: BBox,
    reader: Reader,
    cache: ModelCallCache | None,
    *,
    turn: Turn = 0,
) -> tuple[list[Chunk], bool]:
    """O que `reader` lê dentro de `box`, com caixas e ids levados à página.

    O leitor vê o recorte, girado `turn` graus, e devolve caixas relativas a
    ele; aqui elas voltam às coordenadas da página, e o id é cunhado de novo
    sobre a caixa na página. O recorte não tem ordem de leitura que valha para
    a página.
    """
    region = view.region(box, turn=turn)
    chunks, hit, _ = _read_cached(region, reader, cache)
    page = view.page
    out: list[Chunk] = []
    for chunk in chunks:
        bbox = region.to_page(chunk.bbox)
        out.append(
            chunk.model_copy(
                update={
                    "bbox": bbox,
                    "id": Chunk.make_id(
                        Chunk.key_of(page), bbox, chunk.source, chunk.text, page=page.index
                    ),
                    "reading_order": None,
                    "turn": turn or chunk.turn,
                }
            )
        )
    return out, hit


class _Cascade(NamedTuple):
    """O que a cascata barata leu numa página."""

    chunks: Sequence[Chunk]
    hit: bool
    """Se a leitura principal veio do cache."""
    regions: int
    """Quantas regiões o leitor seguinte leu."""
    failed: list[str]
    """A nota de cada leitor que falhou."""
    lost: bool = False
    """Se as linhas são só parte da página: nenhum outro leu no lugar de quem falhou."""


def _turn_of(chunks: Sequence[Chunk]) -> Turn:
    """O giro da maioria das linhas; o leitor que relê vê a página assim."""
    turns: Counter[Turn] = Counter(c.turn for c in chunks)
    return turns.most_common(1)[0][0] if turns else 0


def _read_cascade(
    view: PageView,
    readers: Sequence[Reader],
    cache: ModelCallCache | None,
    trust_layer: TrustLayer = "visible",
    min_raster: float = 0.0,
) -> _Cascade:
    """Primeiro leitor da cascata que devolve algo, e o que faltar ler.

    A ordem é a que o chamador declarou. Um leitor que volta de mãos vazias
    não encerra a cascata: uma camada de texto presente mas vazia não deve
    impedir o OCR de tentar.

    Com `trust_layer="visible"`, numa página `SEARCHABLE_SCAN` a camada de
    texto não é leitura: ela veio de um OCR desconhecido, e o leitor de
    pixels seguinte lê a página. A camada entra depois, na releitura por
    outra família. Com `"always"`, a camada é lida como está.

    Um leitor que devolve texto sem ter pedido os pixels, que é o caso da
    camada de texto, deixa sem ler os rasters de `page.unread`. O leitor
    seguinte lê o recorte de cada raster com a folga de `RASTER_MARGIN`, e
    ficam as linhas cujo centro cai no raster, menos as que caem em algo já
    lido: o rodapé carimbado sobre uma digitalização já veio da camada de
    texto. Cada uma dessas linhas diz em `region` de qual raster veio, e
    entra na ordem de leitura no lugar do raster (`_in_place`). O recorte, e
    não a página inteira, porque o custo do PP-OCR é por linha reconhecida. É
    assim que a folha digitalizada com o rodapé do PJe carimbado por cima tem o
    corpo lido.

    Um leitor que falha numa página (`RuntimeError`) é como um que volta de
    mãos vazias: a cascata passa ao seguinte, e a falha é contada e avisada.
    Uma página que ninguém leu volta vazia, e a verificação de leitura vazia a
    encaminha ao segundo nível.

    A página lida por um leitor depois da falha de outro não fica incompleta.

    Um raster com área menor que `min_raster` da página não vai ao leitor
    seguinte: o logotipo e o brasão do cabeçalho custariam uma leitura de
    pixels para nada. O raster fica em `Page.unread`, sem linha.
    """
    failed: list[str] = []
    if trust_layer == "visible" and view.page.substrate is Substrate.SEARCHABLE_SCAN:
        readers = [r for r in readers if r.name != TextLayerReader.name]
    for position, reader in enumerate(readers):
        try:
            chunks, hit, rendered = _read_cached(view, reader, cache)
        except RuntimeError as exc:
            failed.append(_warn_failure(reader, view.page, exc))
            continue
        if not chunks:
            continue
        rasters = [(i, b) for i, b in enumerate(view.page.unread) if b.area >= min_raster]
        if rendered or not rasters:
            return _Cascade(chunks, hit, 0, failed)
        for filler in readers[position + 1 :]:
            try:
                extra = _from_rasters(view, filler, cache, chunks, rasters)
            except RuntimeError as exc:
                failed.append(_warn_failure(filler, view.page, exc))
                return _Cascade(chunks, hit, 0, failed, lost=True)
            return _Cascade(_in_place(chunks, extra, view.page.unread), hit, 1, failed)
        return _Cascade(chunks, hit, 0, failed, lost=bool(failed))
    return _Cascade([], False, 0, failed)


def _from_rasters(
    view: PageView,
    reader: Reader,
    cache: ModelCallCache | None,
    read: Sequence[Chunk],
    rasters: Sequence[tuple[int, BBox]],
) -> list[Chunk]:
    """As linhas que `reader` lê nos recortes de `rasters`, com `region` no índice de cada um.

    Cada raster ganha a folga de `RASTER_MARGIN`, e recortes que se tocam
    viram um só, para que o leitor não leia a mesma linha duas vezes. A
    linha no centro de duas regiões que se sobrepõem vem uma vez, com a
    menor delas em `region`. Ficam
    as linhas centradas num raster e em nada já lido: um raster fora de um
    recorte não toca nele, e nenhuma linha dele vem de lá. O raster que ocupa
    a folha inteira, ou um grupo que a cobre, é a página.
    """
    with_margin = [(i, b.padded(RASTER_MARGIN)) for i, b in rasters]
    padded = [(i, (p.x0, p.y0, p.x1, p.y1)) for i, p in with_margin]
    found: list[Chunk] = []
    for _, (x0, y0, x1, y1) in merge_touching(padded):
        if (x0, y0, x1, y1) == (0.0, 0.0, 1.0, 1.0):
            # O grupo que cobre a folha é a página: a mesma leitura, a mesma chave de cache.
            found.extend(_read_cached(view, reader, cache)[0])
        else:
            found.extend(read_region(view, BBox(x0=x0, y0=y0, x1=x1, y1=y1), reader, cache)[0])
    # Duas regiões podem se sobrepor: a área de uma fonte sem mapa por cima
    # da digitalização. A linha fica uma vez, na menor região que a contém.
    out: list[Chunk] = []
    taken: set[str] = set()
    for index, box in sorted(rasters, key=lambda pair: pair[1].area):
        for chunk in _within(found, box):
            if chunk.id in taken or _already_read(chunk.bbox, read):
                continue
            taken.add(chunk.id)
            out.append(chunk.model_copy(update={"region": index}))
    return out


def _in_place(read: Sequence[Chunk], extra: Sequence[Chunk], unread: Sequence[BBox]) -> list[Chunk]:
    """A leitura com as linhas dos rasters no lugar deles, e a ordem de leitura renumerada.

    As linhas de um raster entram juntas, na ordem em que o leitor as
    devolveu, antes da primeira linha já lida cujo topo fica abaixo do topo
    do raster. A ordem do leitor agrupa as linhas da mesma fileira; a ordem
    pelo topo de cada caixa alterna as colunas de uma lista, cujas linhas
    vizinhas diferem por um pixel. O lugar do raster vem da posição: a
    digitalização inteira com o rodapé carimbado por cima tem o corpo antes
    do rodapé, e a figura no meio de uma página composta fica entre o texto
    de cima e o de baixo. Sem detector de layout, a posição é a única ordem
    que a página dá; com detector, `_order_by_layout` refaz a ordem depois.
    """
    if not extra:
        return list(read)
    out = sorted(read, key=lambda c: (c.reading_order is None, c.reading_order or 0, c.bbox.y0))
    by_region: dict[int, list[Chunk]] = {}
    for chunk in extra:
        by_region.setdefault(chunk.region or 0, []).append(chunk)
    for index in sorted(by_region, key=lambda i: (unread[i].y0, unread[i].x0)):
        top = unread[index].y0
        at = next((i for i, c in enumerate(out) if c.bbox.y0 >= top), len(out))
        out[at:at] = by_region[index]
    return [c.model_copy(update={"reading_order": i}) for i, c in enumerate(out)]


def _describe_cheap(chunks: Sequence[Chunk], hit: bool) -> str:
    """O passo do tier barato: quem leu quantas linhas, na ordem em que cada leitor aparece."""
    counts = Counter(c.source for c in chunks)
    read = ", ".join(f"{s} leu {n} linha(s)" for s, n in counts.items()) or "ninguém leu nada"
    return f"tier barato: {read}{_CACHED if hit else ''}"


# ── Composição das leituras ──────────────────────────────────────────────────


def _replace_read(
    cheap: Sequence[Chunk], strong: Sequence[Chunk]
) -> tuple[list[Chunk], list[OtherReading]]:
    """A leitura cara no lugar da barata só onde a cara leu, e a barata que saiu.

    Um leitor por região descarta cabeçalho, rodapé e a tarja da margem, e é
    na tarja que o e-SAJ repete o número do processo. A linha barata cujo
    centro não cai em nenhuma caixa da leitura cara fica, depois das linhas
    caras e sem ordem de leitura. Um leitor da página inteira devolve a caixa
    da página, e então nada da leitura barata fica.

    Fica também a linha barata de uma região que o leitor caro devolveu vazia,
    e a da margem, mesmo que tenha sido ela a disparar a escalada: ninguém a
    releu.

    Cada linha barata que saiu com outro texto vai ao lado da linha cara que
    a cobriu, a de maior interseção entre as que contêm o centro dela.
    """
    kept: list[Chunk] = []
    replaced: list[OtherReading] = []
    for c in cheap:
        if covering := _covering(c.bbox, strong):
            replaced += _replaced(max(covering, key=lambda s: s.bbox.intersection(c.bbox)), c)
        else:
            kept.append(c.model_copy(update={"reading_order": None}))
    return [*strong, *kept], replaced


def _digits(text: str) -> str:
    return re.sub(r"[^0-9]", "", text)


def _explains(check: FailsCheck, value: str, chunk: Chunk) -> bool:
    """Se a linha do leitor caro traz o valor que confere no lugar do inválido.

    Um valor em reais na coluna de uma tabela não tem `R$` na linha, e a forma
    certa dele não é campo. Conta quando há nele um número com vírgula decimal e
    os mesmos dígitos do valor que falhou: só o separador mudou. Com outro
    dígito, ela trouxe outro valor, e nada prova qual dos dois é o certo.
    """
    if check.valid_in(chunk):
        return True
    if check.check is not AMOUNT_BRL:
        return False
    return any(_digits(found) == _digits(value) for found in _BARE_AMOUNT.findall(chunk.text))


def _keeps_digits(failed: str, found: str) -> bool:
    """Se `found` traz, na mesma posição, cada dígito que `failed` traz.

    A pontuação não conta, e a letra de `failed` aceita qualquer caractere:
    `R$ 1.O00,00` aceita `R$ 1.000,00` e recusa `R$ 7.000,00`.
    """
    a, b = re.sub(r"[\W_]", "", failed), re.sub(r"[\W_]", "", found)
    return len(a) == len(b) and all(x == y or not x.isdigit() for x, y in zip(a, b, strict=True))


def _fixes(check: FailsCheck, value: str, chunk: Chunk) -> bool:
    """Se a linha da releitura conserta `value`: traz só valores do campo que conferem.

    Numa regra com redundância, o valor que confere basta. Sem redundância,
    um valor em reais bem escrito com outro dígito confere e pode estar
    errado: a releitura precisa trazer, na mesma posição, cada dígito que a
    leitura barata leu (`_keeps_digits`).
    """
    if not check.valid_in(chunk):
        return False
    if check.check.redundant:
        return True
    return any(_keeps_digits(value, found) for found, _ in check.values(chunk))


def _swap_failing(failing: Sequence[Failure], other: Sequence[Chunk]) -> dict[str, Chunk] | None:
    """O chunk da releitura que conserta cada chunk com valor inválido, pelo id do chunk.

    O chunk da releitura precisa cair no mesmo lugar (o centro de um dentro
    da caixa do outro) e consertar o valor (`_fixes`); entre vários, fica o
    de maior sobreposição com a linha. Se algum valor inválido fica sem
    conserto, nada troca e sai `None`: a página segue ao leitor caro.

    Aqui não vale a regra de `_explains`: uma releitura sem `R$` trocaria a
    linha e tiraria a página do leitor caro.
    """
    swaps: dict[str, Chunk] = {}
    for check, value, chunk in failing:
        candidates = [c for c in other if _same_place(c, chunk) and _fixes(check, value, c)]
        if not candidates:
            return None
        best = max(candidates, key=lambda c: c.bbox.intersection(chunk.bbox))
        swaps[chunk.id] = best.model_copy(update={"reading_order": chunk.reading_order})
    return swaps


def _order_by_layout(chunks: Sequence[Chunk], regions: Sequence[Region]) -> list[Chunk]:
    """As linhas na ordem dos blocos do detector, e de cima para baixo dentro de cada bloco.

    Cada linha vai ao bloco que contém o seu centro, ou ao mais próximo quando
    nenhum a contém, e recebe o rótulo do bloco em `kind` se o leitor não deu
    um. Sem bloco nenhum, a ordem de cada leitor fica como veio.
    """
    if not regions or not chunks:
        return list(chunks)
    by_block: dict[int, list[Chunk]] = {i: [] for i in range(len(regions))}
    for chunk in chunks:
        cx, cy = _centre(chunk.bbox)
        nearest = min(range(len(regions)), key=lambda i: _distance(regions[i].bbox, cx, cy))
        by_block[nearest].append(chunk)
    out: list[Chunk] = []
    for i, block in by_block.items():
        for chunk in sorted(block, key=lambda c: (c.bbox.y0, c.bbox.x0)):
            out.append(
                chunk.model_copy(
                    update={"reading_order": len(out), "kind": chunk.kind or regions[i].label}
                )
            )
    return out


def _stamp_of(form: StampFormat, match: re.Match[str], lines: Sequence[Chunk]) -> Stamp | None:
    """A tarja casada, com as linhas que ela toca, ou None se a data impressa não existe."""
    groups = match.groupdict()
    at = None
    if groups.get("date"):
        printed, layout = groups["date"], form.date_format
        if groups.get("time"):
            printed, layout = f"{printed} {groups['time']}", f"{layout} {form.time_format}"
        try:
            # A hora local que a tarja imprime. O fuso só entra quando o formato o declara.
            at = datetime.strptime(printed, layout)
        except ValueError:
            return None
        if form.tz is not None:
            at = at.replace(tzinfo=ZoneInfo(form.tz))
    process = groups.get("process")
    if process and form.process_check is not None and not form.process_check.is_valid(process):
        return None
    signer = groups.get("signer")
    touched = touched_lines(lines, match.start(), match.end())
    return Stamp(
        format=form.name,
        process=process,
        code=match["code"],
        signer=" ".join(signer.split()) if signer else None,
        at=at,
        protocol=groups.get("protocol"),
        bbox=BBox.envelope([c.bbox for c in touched]),
        chunk_ids=tuple(c.id for c in touched),
    )


type DrawOrder = Callable[[int], Mapping[str, int]]
"""Para o índice de uma página, a posição de desenho de cada linha da camada, pelo `Chunk.id`."""


def _drawn_key(drawn: DrawOrder | None, index: int) -> Callable[[Chunk], tuple[int, int]]:
    """A chave que ordena as linhas da camada pelo desenho, ou pela ordem de leitura sem ele."""
    order: Mapping[str, int] = drawn(index) if drawn is not None else {}
    return lambda c: (order.get(c.id, -1), c.reading_order or 0)


def stamps_of(
    by_page: Mapping[int, Sequence[Chunk]],
    formats: Sequence[StampFormat] = DEFAULT_STAMPS,
    drawn: DrawOrder | None = None,
) -> dict[int, Stamp]:
    """A tarja de cada página, num dos `formats`, pela camada de texto.

    A página copiada de outro processo traz a tarja da origem e a própria. O
    sistema carimba a página ao juntá-la, depois do que ela já trazia, e vale
    a tarja cuja última linha foi desenhada por último. `drawn` dá a ordem de
    desenho, que o pipeline tira do PDF; sem ela, vale a ordem de leitura. A
    tarja casa sempre na ordem de leitura. A regra é da página, e
    vale num PDF que junta peças de vários processos.
    Chama-se antes de reordenar pelo layout.
    """
    out: dict[int, Stamp] = {}
    for index, chunks in by_page.items():
        layer = [c for c in chunks if c.source == TextLayerReader.name]
        stamps = _stamps_in(sorted(layer, key=lambda c: c.reading_order or 0), formats)
        if len(stamps) > 1 and drawn is not None:
            # A tarja casa na ordem do texto; a ordem de desenho escolhe entre
            # as tarjas, pela última linha desenhada de cada uma, e não reordena
            # as linhas: o tribunal desenha a segunda linha da tarja antes da
            # primeira.
            order = drawn(index)
            stamps.sort(key=lambda s: max(order.get(c, -1) for c in s.chunk_ids))
        if stamps:
            out[index] = stamps[-1]
    return out


def _stamps_in(lines: Sequence[Chunk], formats: Sequence[StampFormat]) -> list[Stamp]:
    """As tarjas casadas nas linhas unidas, na ordem das linhas."""
    text = "\n".join(c.text for c in lines)
    found = sorted(
        ((m.start(), form, m) for form in formats for m in form.pattern.finditer(text)),
        key=lambda t: t[0],
    )
    return [s for _, form, m in found if (s := _stamp_of(form, m, lines)) is not None]


def folhas_of(
    by_page: Mapping[int, Sequence[Chunk]],
    checks: Sequence[Check] = (FOLHA,),
    drawn: DrawOrder | None = None,
) -> dict[int, Folha]:
    """A folha carimbada de cada página: o valor de uma das `checks` nas linhas de elemento fixo.

    Cada verificação nomeia o número no grupo `number`, e o verso, quando
    a forma o tem, no grupo `verso`.

    Na camada de texto vale o último carimbo desenhado, pela ordem de
    `drawn`, como em `stamps_of`: o tribunal carimba por cima do que a cópia
    de outro processo já trazia. Sem carimbo na camada, vale o das linhas lidas nos
    pixels, quando elas trazem um valor só. O verso fica de fora. Chama-se
    depois de `mark_furniture` e antes de reordenar pelo layout.
    """
    out: dict[int, Folha] = {}
    for index, chunks in by_page.items():
        fixed = sorted((c for c in chunks if c.furniture), key=lambda c: c.reading_order or 0)
        found = [
            (m["number"].replace(".", ""), m.groupdict().get("verso"), c)
            for c in fixed
            for check in checks
            for m in check.pattern.finditer(fold_lookalikes(c.text))
        ]
        layered = [f for f in found if f[2].source == TextLayerReader.name]
        if len({(n, v) for n, v, _ in layered}) > 1 and drawn is not None:
            by_draw = _drawn_key(drawn, index)
            layered.sort(key=lambda f: by_draw(f[2]))
        if layered:
            number, verso, line = layered[-1]
        elif len({(n, v) for n, v, _ in found}) == 1:
            number, verso, line = found[-1]
        else:
            continue
        if not verso:
            out[index] = Folha(value=int(number), bbox=line.bbox, chunk_ids=(line.id,))
    return out


_DIGITS = re.compile(r"\d+")
_ROMAN = re.compile(r"\b[IVXLC]+\b")
_LETTER = re.compile(r"[^\W\d_]")


def _form_of(text: str) -> str:
    """A forma da linha: dígitos e romanos viram `@`, os espaços colapsam, tudo em minúsculas.

    É o que faz `fls. 12` e `fls. 13`, ou `Página 2 de 9` e `Página 3 de 9`,
    serem a mesma linha.
    """
    return " ".join(_ROMAN.sub("@", _DIGITS.sub("@", text)).split()).lower()


def _has_letter(text: str) -> bool:
    """Se sobra alguma letra depois de mascarar os dígitos e os romanos."""
    return _LETTER.search(_form_of(text)) is not None


def _same_place(a: Chunk, b: Chunk) -> bool:
    """O centro de uma caixa dentro da outra: a mesma linha no mesmo lugar da folha."""
    return _already_read(a.bbox, [b]) or _already_read(b.bbox, [a])


def _as_read(chunk: Chunk) -> BBox:
    """A caixa como a linha é lida: em pé, na página girada `turn` graus."""
    return chunk.bbox.unturned((360 - chunk.turn) % 360)


def _is_vertical(box: BBox) -> bool:
    """Uma linha mais alta que larga é escrita na vertical: a tarja da margem."""
    return box.y1 - box.y0 > box.x1 - box.x0


def _repeated_elsewhere(items: Sequence[Chunk], copy_of: Mapping[int, object]) -> set[str]:
    """Os ids dos trechos de `items` com um igual, no mesmo lugar, em outra página que não é cópia.

    Duas páginas com o mesmo valor em `copy_of` são cópia uma da outra, e a
    repetição entre elas não conta.

    Dois trechos no mesmo lugar têm os centros a menos de meia altura da caixa
    mais alta do grupo; ordenados pelo centro vertical, só esses pares são
    comparados. Um grupo cujas ocorrências estão todas espalhadas pela folha,
    como uma célula de tabela, não custa o quadrado do seu tamanho.
    """
    centred = sorted(((_centre(c.bbox)[1], c) for c in items), key=lambda t: t[0])
    ys = [y for y, _ in centred]
    half = max(c.bbox.y1 - c.bbox.y0 for c in items) / 2
    out: set[str] = set()
    for y, chunk in centred:
        window = centred[bisect_left(ys, y - half) : bisect_right(ys, y + half)]
        own = copy_of[chunk.page]
        if any(copy_of[c.page] != own and _same_place(chunk, c) for _, c in window):
            out.add(chunk.id)
    return out


def mark_furniture(by_page: Mapping[int, Sequence[Chunk]]) -> dict[int, list[Chunk]]:
    """Marca `furniture` na linha que se repete, no mesmo lugar, em outra página: o elemento fixo.

    Candidata é a linha com alguma letra cuja forma (`_form_of`) aparece, com o
    centro de uma caixa dentro da outra, em outra página: repetir é
    categórico, e numa leitura de uma página só nada é elemento fixo.
    Elemento fixo é a candidata numa sequência de candidatas a partir do
    alto ou do pé da página, e a candidata escrita na vertical. Uma linha sem
    letra, como o número da folha, não interrompe a sequência e não é
    marcada: os rótulos de um formulário no meio da página e as listas de
    números ficam de fora. A primeira linha própria da página interrompe a
    sequência, e por isso um carimbo de uma página só dentro do cabeçalho
    deixa o resto do cabeçalho dessa página sem marca.

    A cópia não prova o elemento fixo. Duas páginas com o mesmo conjunto,
    não vazio, de formas nas linhas horizontais com letra são cópia uma da
    outra: a peça
    juntada duas vezes repete o corpo inteiro, e a sequência não pararia.
    A linha vertical da margem fica fora da comparação: ela é marcada quando
    se repete em outra página que não é cópia. Quando todas as páginas lidas
    são cópia umas das outras, não há página diferente, e a regra não vale:
    a peça só de anexos digitalizados fica com o cabeçalho e a folha.

    A linha é julgada como é lida. A sequência corre por giro: a camada de texto
    de uma página lida de lado continua em pé, e as duas leituras não têm o mesmo
    alto nem o mesmo pé.

    Sem limiar. A marca não apaga a linha.
    A repetição é vista sobre as páginas de `by_page`: a mesma linha pode
    sair marcada numa execução do documento inteiro e sem marca numa de
    poucas páginas.
    """
    by_form: dict[str, list[Chunk]] = defaultdict(list)
    forms: defaultdict[int, set[str]] = defaultdict(set)
    for chunks in by_page.values():
        for chunk in chunks:
            form = _form_of(chunk.text)
            if _LETTER.search(form):
                by_form[form].append(chunk)
                if not _is_vertical(_as_read(chunk)):
                    forms[chunk.page].add(form)
    copy_of = {c.page: frozenset(forms[c.page]) or c.page for cs in by_page.values() for c in cs}
    if len(set(copy_of.values())) == 1:
        # Todas cópia de todas: não há página diferente que prove nada.
        copy_of = {page: page for page in copy_of}
    repeated = set[str]().union(
        *(_repeated_elsewhere(items, copy_of) for items in by_form.values())
    )
    out: dict[int, list[Chunk]] = {}
    for index, chunks in by_page.items():
        marked = {c.id for c in chunks if c.id in repeated and _is_vertical(_as_read(c))}
        for turn in {c.turn for c in chunks}:
            horizontal = sorted(
                (c for c in chunks if c.turn == turn and not _is_vertical(_as_read(c))),
                key=lambda c: (_as_read(c).y0, _as_read(c).x0),
            )
            for sequence in (horizontal, reversed(horizontal)):
                for chunk in sequence:
                    if chunk.id in repeated:
                        marked.add(chunk.id)
                    elif _has_letter(chunk.text):
                        break
        out[index] = [
            c.model_copy(update={"furniture": True}) if c.id in marked else c for c in chunks
        ]
    return out


# ── A execução ───────────────────────────────────────────────────────────────


def _float_counter() -> defaultdict[str, float]:
    return defaultdict(float)


def _step_lists() -> defaultdict[int, list[str]]:
    return defaultdict(list)


def _page_seconds() -> defaultdict[int, dict[str, float]]:
    return defaultdict(dict)


@dataclass
class _Run:
    """O estado que as etapas de `process` partilham sobre um documento aberto.

    `spent` conta o que cada etapa gastou, com as chaves de `Result.spent`;
    `steps` guarda, por página, uma frase por passo; `regions` são os blocos
    do detector de layout, detectados uma vez por página, na primeira vez que
    a página é vista.
    """

    handle: pdfium.PdfDocument
    cache: ModelCallCache | None
    dpi: int | None
    layout: Layout | None
    min_raster: float = 0.0
    """A fração da página abaixo da qual um raster não lido não vai ao leitor de pixels."""
    spent: defaultdict[str, float] = field(default_factory=_float_counter)
    steps: defaultdict[int, list[str]] = field(default_factory=_step_lists)
    regions: dict[int, list[Region]] = field(default_factory=dict[int, list[Region]])
    views: dict[int, PageView] = field(default_factory=dict[int, PageView])
    """As vistas das páginas ainda em curso: a renderização de uma etapa serve à seguinte."""
    others: list[OtherReading] = field(default_factory=list[OtherReading])
    """As outras leituras de uma linha, e as linhas substituídas, para `Result.others`."""
    failures: defaultdict[int, list[str]] = field(default_factory=_step_lists)
    """Por página, a nota de cada leitor que falhou, para `RoutingDecision.failures`."""
    incomplete: set[int] = field(default_factory=set[int])
    """As páginas em que um leitor falhou e nenhum outro leu, para `RoutingDecision.incomplete`."""
    seconds: defaultdict[int, dict[str, float]] = field(default_factory=_page_seconds)
    """Por página, os segundos de cada etapa que a tocou, para `RoutingDecision.seconds`."""

    def view(self, page: Page) -> PageView:
        """A vista da página, guardada se a página ainda está em curso; senão, uma nova."""
        kept = self.views.get(page.index)
        return kept if kept is not None else PageView(self.handle, page, dpi=self.dpi)

    def keep(self, indices: Container[int]) -> None:
        """Solta as vistas das páginas fora de `indices`: a renderização delas não serve mais."""
        for index in [i for i in self.views if i not in indices]:
            del self.views[index]

    def detect(self, view: PageView) -> bool:
        """Os blocos de layout da página, uma vez só; True se vieram do cache.

        A vista fica com os blocos e a versão do detector: um leitor caro com
        o mesmo detector os reaproveita em vez de detectar de novo. Cada
        página passa por aqui numa thread só por etapa, e as etapas são
        sequenciais: nada disputa a entrada de uma página.
        """
        if self.layout is None:
            return False
        hit = False
        if view.page.index not in self.regions:
            self.regions[view.page.index], hit = _regions_cached(view, self.layout, self.cache)
        view.regions = self.regions[view.page.index]
        view.regions_version = self.layout.output_version
        return hit

    @contextmanager
    def timed(self, key: str) -> Generator[None]:
        """Soma a `spent[key]` os segundos do bloco."""
        tick = time.perf_counter()
        try:
            yield
        finally:
            self.spent[key] += time.perf_counter() - tick


def _cheap_stage(
    run: _Run,
    batch: Sequence[Page],
    readers: Sequence[Reader],
    workers: int,
    trust_layer: TrustLayer = "visible",
    keep: Callable[[Page, Sequence[Chunk]], bool] | None = None,
) -> dict[int, Sequence[Chunk]]:
    """Lê `batch` no tier barato, e detecta o layout de cada página na mesma renderização.

    A vista de uma página fica guardada para a etapa seguinte só se `keep`
    diz que a página ainda pode escalar. As outras soltam a renderização ao
    sair daqui, e a memória do tier barato não cresce com o documento.
    """

    def read_one(
        page: Page,
    ) -> tuple[PageView | None, _Cascade, bool]:
        tick = time.perf_counter()
        view = run.view(page)
        read = _read_cascade(view, readers, run.cache, trust_layer, run.min_raster)
        layout_hit = run.detect(view)
        run.seconds[page.index]["cheap"] = time.perf_counter() - tick
        # A vista sai daqui só se fica guardada; a lista de resultados não
        # segura a renderização de todas as páginas até o fim da etapa.
        kept = view if keep is not None and keep(page, read.chunks) else None
        return kept, read, layout_hit

    # Todas as threads partilham o mesmo documento aberto. O acesso ao pdfium
    # passa pelo lock de `docaudit.pdf`; o OCR, que domina o tempo, roda fora
    # dele. A detecção de layout usa a mesma renderização, e o tempo dela
    # entra nesta etapa.
    with run.timed("seconds_cheap"):
        if workers > 1 and batch:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(read_one, batch))
        else:
            results = list(map(read_one, batch))
    out: dict[int, Sequence[Chunk]] = {}
    for page, (view, read, layout_hit) in zip(batch, results, strict=True):
        if view is not None:
            run.views[page.index] = view
        run.spent["pages_cheap_cached"] += read.hit
        run.spent["regions_cheap"] += read.regions
        run.spent["pages_cheap_failed"] += bool(read.failed)
        run.failures[page.index].extend(read.failed)
        if read.lost:
            run.incomplete.add(page.index)
        run.spent["pages_layout_cached"] += layout_hit
        run.steps[page.index].append(_describe_cheap(read.chunks, read.hit))
        out[page.index] = read.chunks
    return out


type Failure = tuple[FailsCheck, str, Chunk]
"""Um valor que falha uma verificação: a verificação, o valor e a linha em que ele está."""


def _failures(checks: Sequence[FailsCheck], page: Page, chunks: Sequence[Chunk]) -> list[Failure]:
    """Cada valor que falha uma verificação na leitura da página, uma vez por linha que ele toca."""
    return [(c, value, chunk) for c in checks for value, chunk in c.failing(page, chunks)]


def _repeats(value: str, chunk: Chunk) -> bool:
    """Se a linha traz o valor inválido, com hífens e espaços tipográficos já em ASCII."""
    return value in " ".join(fold_lookalikes(chunk.text).split())


def _printed(
    entity: Entity,
    page: Page,
    lines: Sequence[Chunk],
    same_by_line: Mapping[str, Sequence[OtherReading]],
    alike: Mapping[str, Callable[[str], bool]],
) -> Entity:
    """A entidade que falha, com quem mostra que o erro é do documento, se alguém mostra.

    As duas provas da cascata: o valor só está em texto composto, que nenhum
    leitor reconheceu; ou outra família leu o mesmo valor inválido na linha.
    A segunda não vale na troca que as famílias fazem juntas, em `alike`, pelo
    nome da verificação.
    """
    if entity.state is not EntityState.FAILED:
        return entity
    touched = [c for c in lines if c.id in entity.chunk_ids]
    if not _machine_chunks(page, touched):
        return entity.model_copy(update={"printed": TextLayerReader.name})
    if (shared := alike.get(entity.kind)) is not None and shared(entity.value):
        return entity
    for line in entity.chunk_ids:
        for other in same_by_line.get(line, ()):
            if _repeats(entity.value, other.reading):
                return entity.model_copy(update={"printed": other.reading.source})
    return entity


def _other_readings(failures: Sequence[Failure], other: Sequence[Chunk]) -> list[OtherReading]:
    """As linhas de `other` no lugar de cada linha que falha, com o veredito de cada uma.

    Uma linha com dois valores inválidos aparece uma vez por par: `same` diz
    se a outra leitura repete algum deles.
    """
    values: dict[str, tuple[Chunk, list[str]]] = {}
    for _check, value, line in failures:
        values.setdefault(line.id, (line, []))[1].append(value)
    return [
        OtherReading(line=line.id, reading=o, same=any(_repeats(v, o) for v in printed))
        for line, printed in values.values()
        for o in other
        if _same_place(o, line)
    ]


def _confirm_stage(
    run: _Run,
    decisions: list[RoutingDecision],
    pages: Mapping[int, Page],
    reads: dict[int, Sequence[Chunk]],
    failures: dict[int, list[Failure]],
    checks: Sequence[FailsCheck],
    layer: Reader | None,
    confirm: Reader | None,
) -> None:
    """Relê, com outra família, a página encaminhada por uma verificação.

    Duas famílias que devolvem o mesmo valor inválido confirmam o erro do
    documento, salvo na troca que as famílias fazem juntas (`Check.alike`);
    um valor que confere no mesmo lugar conserta a linha, e num campo sem
    redundância só quando mantém os dígitos lidos (`_fixes`). "Vale o
    valor válido" seria a regra errada: uma leitura errada pode conferir.
    Numa `SEARCHABLE_SCAN` a primeira família é a camada de OCR embutida,
    que já está lida e custa zero; depois vem `confirm`. A primeira que
    decide encerra. Muda `decisions`, `reads` e `failures` no lugar.
    """
    for k, decision in enumerate(decisions):
        if decision.tier is not Tier.STRONG:
            continue
        page = pages[decision.page]
        chunks = reads.get(page.index, ())
        before = failures.get(page.index, [])
        if not before:
            continue
        families = [
            b
            for b in (layer if page.substrate is Substrate.SEARCHABLE_SCAN else None, confirm)
            if b is not None
        ]
        tick = time.perf_counter()
        view = run.view(page)
        steps = run.steps[page.index]
        values = ", ".join(dict.fromkeys(value for _, value, _ in before))
        failing = {(c.name, value) for c, value, _ in before}
        alike = ", ".join(
            dict.fromkeys(v for c, v, _ in before if c.check.alike is not None and c.check.alike(v))
        )
        for backend in families:
            who = f"releitura por {backend.name}"
            try:
                other, hit, _ = _read_cached(view, backend, run.cache)
            except RuntimeError as exc:
                run.failures[page.index].append(_warn_failure(backend, page, exc))
                steps.append(f"{who} falhou: {exc}")
                continue
            run.spent["pages_confirmed"] += 1
            run.spent["pages_confirm_cached"] += hit
            # A leitura que consertou substitui a linha, e o filtro do fim a tira.
            run.others.extend(_other_readings(before, other))
            after = {(c.name, value) for c in checks for value, _ in c.failing(page, other)}
            if after == failing and alike:
                steps.append(
                    f"{who}: leu o mesmo valor inválido ({values}), "
                    f"mas {alike} é troca que as famílias fazem juntas"
                )
                continue
            if after == failing:
                run.spent["pages_confirmed_same"] += 1
                decisions[k] = decision.model_copy(
                    update={
                        "tier": Tier.CHEAP,
                        "reason": f"erro do documento: {backend.name} leu o mesmo",
                    }
                )
                steps.append(
                    f"{who}: leu o mesmo valor inválido ({values}); "
                    "o erro está impresso no documento, fica a leitura barata"
                )
                break
            if not after and (swapped := _swap_failing(before, other)) is not None:
                run.spent["pages_confirmed_fixed"] += 1
                reads[page.index] = [swapped.get(c.id, c) for c in chunks]
                for c in chunks:
                    if c.id in swapped:
                        run.others += _replaced(swapped[c.id], c)
                failures[page.index] = []
                decisions[k] = decision.model_copy(
                    update={"tier": Tier.CHEAP, "reason": f"corrigido por {backend.name}"}
                )
                steps.append(
                    f"{who}: valor que confere no mesmo lugar; "
                    f"{len(swapped)} linha(s) trocada(s), fica a leitura barata"
                )
                break
            steps.append(f"{who}: outro valor ({values} antes)")
        else:
            if families:
                steps.append("nenhuma releitura explicou o valor; segue ao leitor caro")
        run.seconds[page.index]["confirm"] = time.perf_counter() - tick


def _valid_values(check: FailsCheck, chunk: Chunk) -> set[str]:
    """Os valores do campo que conferem no chunk, sem espaços, para comparar entre leitores."""
    return {"".join(value.split()) for value, valid in check.values(chunk) if valid}


_BARE_AMOUNT = re.compile(r"(?<![0-9.,])[0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}(?![0-9.,])")
"""O número com vírgula decimal e milhar com ponto, com ou sem o `R$` antes."""


def _amount_disagreements(
    run: _Run, page: Page, lines: Sequence[Chunk], trust_layer: TrustLayer
) -> list[OtherReading]:
    """As linhas da camada oculta que leem outro número no lugar de um valor lido dos pixels.

    O valor em reais não tem dígito verificador: lido errado e bem escrito,
    nenhuma regra o vê. Numa digitalização com camada de OCR, a camada é outra
    família, já paga. Cada linha lida dos pixels com valores é comparada com
    as linhas da camada no mesmo lugar, da esquerda para a direita; com o
    mesmo número de valores, o primeiro par diferente vira uma leitura ao
    lado, com `same=False`, o `check` e o valor da linha. Só aponta: não
    corrige nem escala. A página sem valor lido dos pixels não lê a camada.
    """
    if trust_layer != "visible" or page.substrate is not Substrate.SEARCHABLE_SCAN:
        return []
    read = [
        (line, mine)
        for line in lines
        if line.source != TextLayerReader.name
        and (mine := _BARE_AMOUNT.findall(fold_lookalikes(line.text)))
    ]
    if not read:
        return []
    hidden, _, _ = _read_cached(run.view(page), TextLayerReader(), run.cache)
    out: list[OtherReading] = []
    for line, mine in read:
        near = sorted((h for h in hidden if _same_place(h, line)), key=lambda h: h.bbox.x0)
        theirs = [(a, h) for h in near for a in _BARE_AMOUNT.findall(fold_lookalikes(h.text))]
        if len(theirs) != len(mine):
            continue
        for a, (b, h) in zip(mine, theirs, strict=True):
            if a != b:
                out.append(
                    OtherReading(
                        line=line.id, reading=h, same=False, check=AMOUNT_BRL.name, value=a
                    )
                )
                break
    return out


def _draw_order_of(run: _Run, pages: Mapping[int, Page]) -> DrawOrder:
    """A ordem de desenho das linhas da camada de cada página, lida do PDF só quando pedida."""

    def order(index: int) -> Mapping[str, int]:
        page = pages[index]
        return {
            Chunk.make(page, d.line.bbox, TextLayerReader.name, d.line.text).id: d.drawn
            for d in _pdf.drawn_lines_of(run.handle, index)
        }

    return order


def _in_sequence(folhas: Mapping[int, Folha]) -> dict[int, Folha]:
    """As folhas, com `in_sequence` onde a folha menos o índice da página é a diferença mais comum.

    Num auto sem página faltando, a folha sobe uma por página, e a diferença
    é uma só. A folha que não a segue é a de um documento juntado com
    numeração própria, ou a de uma cópia. Uma diferença que só uma página tem não
    confirma nada. O verso digitalizado ocupa uma página sem folha, e com ele
    a diferença muda a cada folha.
    """
    offsets = Counter(f.value - index for index, f in folhas.items())
    best, count = offsets.most_common(1)[0] if offsets else (None, 0)
    return {
        index: f.model_copy(update={"in_sequence": count > 1 and f.value - index == best})
        for index, f in folhas.items()
    }


def _confirmed_keys(
    checks: Sequence[Check], page: Page, chunks: Sequence[Chunk]
) -> set[tuple[str, str]]:
    """O campo e os dígitos de cada valor que confere em `chunks`, na ordem de leitura."""
    ordered = sorted(chunks, key=reading_order_key)
    return {
        (e.kind, re.sub(r"\D", "", e.value))
        for e in entities_of(checks, page, ordered)
        if e.state is EntityState.CONFIRMED
    }


def _with_layer(
    run: _Run, page: Page, lines: Sequence[Chunk], checks: Sequence[Check], trust_layer: TrustLayer
) -> tuple[list[Chunk], list[OtherReading]]:
    """A leitura com as linhas da camada oculta que trazem um id que os pixels não confirmaram.

    Numa digitalização com camada de OCR, `trust_layer="visible"` lê os
    pixels, e a camada é outra família, já paga. Um id com dígito
    verificador que confere na camada é prova por si (`Check.redundant`):
    a linha dela entra no lugar das linhas dos pixels no mesmo lugar da
    folha, e cada linha trocada fica em `Result.others` com `replaced`. A
    linha dos pixels que confirma um valor que a da camada não traz fica, e
    a da camada entra antes dela. Sem linha dos pixels no lugar, a da camada
    entra pela posição. Um valor sem redundância, lido de outro jeito na
    camada, não diz qual leitura está certa, e não troca nada.
    """
    redundant = [c for c in checks if c.redundant]
    if not redundant or trust_layer != "visible" or page.substrate is not Substrate.SEARCHABLE_SCAN:
        return list(lines), []
    hidden, _, _ = _read_cached(run.view(page), TextLayerReader(), run.cache)
    seen = _confirmed_keys(redundant, page, lines)
    layer = [
        h for h in hidden if (keys := _confirmed_keys(redundant, page, [h])) and not keys <= seen
    ]
    return _in_place_of_pixels(page, lines, layer, redundant)


def _in_place_of_pixels(
    page: Page, lines: Sequence[Chunk], layer: Sequence[Chunk], redundant: Sequence[Check]
) -> tuple[list[Chunk], list[OtherReading]]:
    """`lines` com cada linha de `layer` no lugar das linhas dos pixels que ela cobre.

    Sai a linha dos pixels no mesmo lugar que tem a maior parte da área
    dentro da linha da camada, para `Result.others`, com `replaced`. Fica a
    que confirma um valor que a da camada não traz, e a que passa muito dela
    dos dois lados: a linha curta da camada
    dentro de um cabeçalho lido pelos pixels não apaga o cabeçalho. Nos dois
    casos a da camada entra antes. Sem linha dos pixels no lugar, a da camada
    entra pela posição, e as que vêm seguidas assim ficam na ordem de
    `layer`, a ordem em que a tarja casou.
    """
    if not layer:
        return list(lines), []
    out = sorted(lines, key=reading_order_key)
    others: list[OtherReading] = []
    after: int | None = None
    for line in layer:
        brought = _confirmed_keys(redundant, page, [line])
        same = [
            i
            for i, c in enumerate(out)
            if c.source != TextLayerReader.name and _same_place(c, line)
        ]
        gone = [
            i
            for i in same
            if 2 * out[i].bbox.intersection(line.bbox) >= out[i].bbox.area
            and _confirmed_keys(redundant, page, [out[i]]) <= brought
        ]
        if same:
            at = min(same)
        elif after is not None:
            at = after
        else:
            at = next((i for i, c in enumerate(out) if c.bbox.y0 > line.bbox.y0), len(out))
        others.extend(
            OtherReading(line=line.id, reading=out[i], same=False, replaced=True) for i in gone
        )
        kept = [c for i, c in enumerate(out) if i not in gone]
        at -= sum(1 for i in gone if i < at)
        out = [*kept[:at], line, *kept[at:]]
        after = None if same else at + 1
    return [c.model_copy(update={"reading_order": i}) for i, c in enumerate(out)], others


def _with_visible_stamps(
    run: _Run,
    page: Page,
    lines: Sequence[Chunk],
    formats: Sequence[StampFormat],
    folha_checks: Sequence[Check],
    checks: Sequence[Check],
    trust_layer: TrustLayer,
) -> tuple[list[Chunk], list[OtherReading]]:
    """A leitura com as linhas à vista da camada que formam a tarja ou o carimbo de folha.

    Numa digitalização com camada de OCR, `trust_layer="visible"` não lê a
    camada, e a camada inteira fica de fora: também a tarja que o tribunal
    desenha com tinta por cima da imagem, texto exato. A linha à vista
    (`drawn_lines_of`) que entra numa tarja de `formats`, ou que é inteira
    uma folha de `folha_checks`, entra no lugar das linhas dos pixels no
    mesmo lugar, como em `_with_layer`. O resto da página segue dos pixels.
    """
    if trust_layer != "visible" or page.substrate is not Substrate.SEARCHABLE_SCAN:
        return list(lines), []
    # Na ordem do texto do pdfium, em que a tarja casa: a de desenho a parte.
    drawn = [d for d in _pdf.drawn_lines_of(run.handle, page.index) if d.visible]
    if not drawn:
        return list(lines), []
    visible = [
        Chunk.make(page, d.line.bbox, TextLayerReader.name, d.line.text, reading_order=i)
        for i, d in enumerate(drawn)
    ]
    picked = {i for s in _stamps_in(visible, formats) for i in s.chunk_ids}
    for chunk in visible:
        folded = fold_lookalikes(chunk.text).strip()
        if any(check.pattern.fullmatch(folded) for check in folha_checks):
            picked.add(chunk.id)
    taken = {c.id for c in lines}
    layer = [c for c in visible if c.id in picked and c.id not in taken]
    return _in_place_of_pixels(page, lines, layer, [c for c in checks if c.redundant])


def _rejected_strong(
    cheap: Sequence[Chunk],
    strong: Sequence[Chunk],
    failures: Sequence[Failure],
    checks: Sequence[FailsCheck],
) -> tuple[set[str], list[str]]:
    """As linhas da leitura cara que não entram no lugar da barata, e o porquê de cada recusa.

    A leitura cara passa pelas mesmas verificações que a barata, com o
    veredito da releitura por outra família. Uma linha cara que cobre uma
    linha barata com um valor que confere, e não traz esse valor, perdeu o
    valor: fica a linha barata. O mesmo vale para o número com vírgula
    decimal e milhar no lugar, mesmo sem o `R$` na linha: numa tabela, o
    símbolo fica no cabeçalho ou na linha de cima, e a linha cara que lê o
    ponto no lugar da vírgula perde o valor. Esse número não tem dígito
    verificador, e a linha barata fica mesmo quando a cara leu outro valor
    bem formado. Para um valor que falhou na leitura barata, a linha cara
    no mesmo lugar que traz o valor que confere conserta; a que traz o
    mesmo valor inválido não conserta, e a barata fica; a que traz outra
    coisa não explicou nada, e a barata fica. O leitor caro não é declarado
    de outra família, e por isso a repetição dele não prova erro do
    documento: o padrão é um PP-OCR maior, que erra junto com o barato.
    """
    rejected: set[str] = set()
    # O porquê de cada recusa, uma vez cada, na ordem em que aparece.
    notes: dict[str, None] = {}
    covering = {line.id: _covering(line.bbox, strong) for line in cheap}
    for check in checks:
        carried = {s.id: _valid_values(check, s) for s in strong}
        for line in cheap:
            values: set[str] = _valid_values(check, line) if covering[line.id] else set()
            for s in covering[line.id]:
                if values and not values <= carried[s.id]:
                    rejected.add(s.id)
                    notes[f"perdeu {check.name} que a leitura barata trazia"] = None
    amounts = {s.id: set(_BARE_AMOUNT.findall(s.text)) for s in strong}
    for line in cheap:
        values = set(_BARE_AMOUNT.findall(line.text)) if covering[line.id] else set()
        for s in covering[line.id]:
            if values and not values <= amounts[s.id]:
                rejected.add(s.id)
                notes["perdeu um valor com vírgula decimal que a leitura barata trazia"] = None
    for check, value, line in failures:
        covering = [s for s in strong if _same_place(line, s)]
        if not covering or any(_explains(check, value, s) for s in covering):
            continue
        rejected.update(s.id for s in covering)
        same = any(_repeats(value, s) for s in covering)
        note = (
            f"leu o mesmo valor inválido ({value}); os dois leitores podem errar juntos"
            if same
            else f"outro valor no lugar de {check.name} ({value}); não explicou"
        )
        notes[note] = None
    return rejected, list(notes)


class _StrongRead(NamedTuple):
    """O que o leitor caro devolveu para uma página, antes de entrar no resultado."""

    page: Page
    strong: list[Chunk]
    hit: bool
    scope: str
    by_region: bool
    error: RuntimeError | None
    layout_hit: bool
    """Se os blocos de layout da página vieram do cache."""


def _strong_one(
    run: _Run,
    page: Page,
    boxes: Mapping[BBox, Turn],
    turn: Turn,
    backend: Reader,
) -> _StrongRead:
    """Lê uma página no tier caro: os recortes de `boxes`, ou a página inteira sem eles.

    O leitor vê em pé o que a leitura barata leu de lado: cada recorte com o
    giro dele, e a página inteira com `turn`. Os blocos de layout são
    detectados antes da leitura, na mesma renderização, para que um leitor
    com o mesmo detector os reaproveite.
    """
    view = run.view(page)
    layout_hit = run.detect(view)
    try:
        if boxes:
            strong: list[Chunk] = []
            hit = True
            for box, box_turn in boxes.items():
                found, found_hit = read_region(view, box, backend, run.cache, turn=box_turn)
                strong.extend(_within(found, box))
                hit = hit and found_hit
            scope = f"{len(boxes)} recorte(s) das linhas que falharam"
            return _StrongRead(page, strong, hit, scope, True, None, layout_hit=layout_hit)
        if turn:
            whole = BBox(x0=0.0, y0=0.0, x1=1.0, y1=1.0)
            found, hit = read_region(view, whole, backend, run.cache, turn=turn)
            read = [c.model_copy(update={"reading_order": i}) for i, c in enumerate(found)]
        else:
            cached, hit, _ = _read_cached(view, backend, run.cache)
            read = list(cached)
        return _StrongRead(page, read, hit, "a página inteira", False, None, layout_hit=layout_hit)
    except RuntimeError as exc:
        return _StrongRead(page, [], False, "", bool(boxes), exc, layout_hit=layout_hit)


def _strong_stage(
    run: _Run,
    pages: Sequence[Page],
    decisions: Mapping[int, RoutingDecision],
    by_page: dict[int, Sequence[Chunk]],
    failures: Mapping[int, Sequence[Failure]],
    backend: Reader | None,
    checks: Sequence[FailsCheck],
    reread: Reread,
    workers: int,
    deadline: float | None,
) -> set[int]:
    """Lê no tier caro cada página escalada, inteira ou só as regiões que falharam.

    Um leitor local vai página a página: o paralelismo que compensa nele é
    dentro da página, entre regiões, e é o leitor quem o faz
    (`VLM(concurrency=...)`); páginas inteiras em paralelo só disputariam a
    mesma GPU. Um leitor hospedado (`external`) espera a rede, e as páginas
    vão em paralelo, `workers` de cada vez. O resultado entra na ordem das
    páginas nos dois casos.

    `deadline` é o instante de `time.perf_counter` em que `Budget.max_seconds`
    vence: a página que começa depois dele não vai ao leitor caro. Devolve os
    índices dessas páginas, para que quem chama garanta a leitura barata delas.
    """
    deferred: set[int] = set()
    if backend is None:
        for page in pages:
            run.steps[page.index].append("sem leitor caro: fica a leitura barata")
        return deferred
    check_names = {c.name for c in checks}

    def boxes_of(page: Page) -> dict[BBox, Turn]:
        # Por região, a verificação diz onde a leitura falhou, e o leitor
        # caro lê só ali: um recorte por valor inválido, cobrindo as linhas
        # em que o valor está, que são duas quando ele quebra na linha. Se
        # disparou também um sinal que não aponta linha, como leitura vazia
        # ou texto mal decodificado, o recorte deixaria o resto da falha na
        # página: ela vai inteira.
        pointed = reread == "region" and set(decisions[page.index].signals) <= check_names
        if not pointed:
            return {}
        lines: dict[tuple[str, str], list[Chunk]] = {}
        for check, value, chunk in failures.get(page.index, ()):
            lines.setdefault((check.name, value), []).append(chunk)
        return {BBox.envelope([c.bbox for c in ls]): _turn_of(ls) for ls in lines.values()}

    def one(page: Page) -> _StrongRead | None:
        """A leitura cara da página, ou None quando o teto de tempo chegou antes dela."""
        tick = time.perf_counter()
        if deadline is not None and tick >= deadline:
            return None
        turn = _turn_of(by_page.get(page.index, ()))
        read = _strong_one(run, page, boxes_of(page), turn, backend)
        run.seconds[page.index]["strong"] = time.perf_counter() - tick
        return read

    if backend.external and workers > 1 and len(pages) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            reads = list(pool.map(one, pages))
    else:
        reads = [one(page) for page in pages]
    for page, read in zip(pages, reads, strict=True):
        steps = run.steps[page.index]
        cheap = by_page.get(page.index, ())
        if read is None:
            deferred.add(page.index)
            steps.append("teto de tempo do orçamento atingido antes desta página: fica a barata")
            continue
        if read.error is not None:
            # O leitor caro recusou esta página: ela fica com a leitura
            # barata, quando houve, e o auto segue. Um servidor ausente
            # (`ConnectionError`) não é por página e sobe.
            run.failures[page.index].append(_warn_failure(backend, page, read.error))
            run.spent["pages_strong_failed"] += 1
            steps.append(f"{backend.name} falhou: {read.error}; fica a leitura barata, se houve")
        else:
            fails = failures.get(page.index, ())
            rejected, notes = _rejected_strong(cheap, read.strong, fails, checks)
            accepted = [s for s in read.strong if s.id not in rejected]
            refused = [s for s in read.strong if s.id in rejected]
            run.others.extend(_other_readings(fails, refused))
            merged, replaced = _replace_read(cheap, accepted)
            run.others.extend(replaced)
            # A linha barata que sobra fora das caixas do leitor caro fica
            # porque ninguém a releu. A linha mal decodificada é a exceção
            # quando o leitor caro leu a folha inteira: ela é lixo por
            # definição, e descartá-la não perde nada.
            if GarbledText.name in decisions[page.index].signals and not read.by_region:
                strong_ids = {s.id for s in accepted}
                clean = [c for c in merged if c.id in strong_ids or not garbled_runs(c.text)]
                if len(clean) < len(merged):
                    steps.append(
                        f"{len(merged) - len(clean)} linha(s) mal decodificada(s) fora das "
                        "caixas do leitor caro descartada(s)"
                    )
                merged = clean
            by_page[page.index] = merged
            if not read.by_region:
                run.incomplete.discard(page.index)
            kept = len(merged) - len(accepted)
            run.spent["pages_strong"] += 1
            run.spent["pages_strong_cached"] += read.hit
            run.spent["regions_strong"] += read.by_region
            run.spent["lines_strong_rejected"] += len(rejected)
            steps.append(
                f"{backend.name} leu {read.scope}: {len(read.strong)} linha(s); "
                f"substituiu {len(cheap) - kept} da leitura barata, ficaram {kept}"
                f"{_CACHED if read.hit else ''}"
            )
            if rejected:
                steps.append(
                    f"{len(rejected)} linha(s) do leitor caro recusada(s): " + "; ".join(notes)
                )
        run.spent["pages_layout_cached"] += read.layout_hit
    return deferred


def process(
    document: Path | str | bytes,
    *,
    policy: TriagePolicy | str = "all_cheap",
    budget: Budget | None = None,
    cheap: Sequence[Reader | str] = DEFAULT_CASCADE,
    strong: Reader | str | None = None,
    confirm: Reader | str | None = None,
    reread: Reread = "page",
    layout: Layout | None = None,
    trust_layer: TrustLayer = "visible",
    entities: Sequence[Check] | None = None,
    stamps: Sequence[StampFormat | str] | None = None,
    folhas: Sequence[Check | str] | None = None,
    spans: bool = False,
    allow_external: bool = False,
    cache: ModelCallCache | None = None,
    dpi: int | None = None,
    workers: int = 1,
    pages: Container[int] | None = None,
    min_raster_fraction: float = 0.0,
) -> Result:
    """Lê um documento, confere a leitura e devolve os trechos lidos.

    Args:
        document: caminho do PDF, como `Path` ou `str`, ou seus bytes.
        policy: política de triagem, ou o nome de uma embutida. O padrão,
            `all_cheap`, não encaminha nenhuma página. `evidence` lê tudo no
            tier barato e encaminha só onde a leitura provou ter falhado.
        budget: teto opcional do leitor caro, em páginas e em segundos
            (`max_seconds`). Sem ele, a política encaminha toda página em que
            achou evidência. O teto de páginas vale para qualquer política, e
            o que passar dele fica em `CHEAP`. `evidence` corta na ordem de
            prioridade dos sinais, e o motivo da página cortada é o do sinal.
            As outras políticas são cortadas na ordem em que devolvem as
            decisões, e o motivo diz que a página ficou fora do teto. A
            página que o leitor caro começaria depois de `max_seconds` fica
            com a leitura barata, e o motivo vai em
            `RoutingDecision.steps`. Tokens e dólares não têm teto: são
            relatados em `Result.spent`.
        cheap: a cascata do tier barato, em ordem de preferência. A primeira
            leitura não vazia vence. O padrão lê a camada de texto onde
            houver e manda o resto ao PP-OCR. Numa `SEARCHABLE_SCAN`, com o
            padrão `trust_layer="visible"`, a camada não é a leitura, e os
            pixels vão ao leitor seguinte.
        strong: leitor caro, como instância ou nome de um leitor registrado por
            entry point. É o mesmo contrato dos leitores baratos; o que muda é
            quem decide chamá-lo. `None` desliga a escalada: a decisão da
            política fica em `decisions`, e toda página é lida só no barato.
        confirm: leitor de outra família que relê, antes do leitor caro, a
            página encaminhada com um valor que falha uma verificação
            (`FailsCheck`). Se a releitura
            devolve os mesmos valores inválidos, o erro é do documento e a
            página fica em `CHEAP`, com o motivo dizendo isso. Se a releitura
            traz, no lugar de cada valor inválido, um valor que confere, essas
            linhas trocam e a página também fica em `CHEAP`. Nos outros casos
            a página segue ao leitor caro. A releitura vale para toda página
            encaminhada em que um valor falha uma verificação, qualquer que
            seja o sinal que a encaminhou. A página sem valor que falha, como a
            de leitura vazia, segue direto ao leitor caro. `None` desliga.
        reread: o que o leitor caro recebe de uma página encaminhada.
            `"page"`, o padrão, é a página inteira. `"region"` é um recorte
            por linha da leitura barata com um valor que falha uma
            verificação, e o leitor caro substitui só o que leu ali.
            A página vai inteira, nos dois modos, quando disparou nela um
            sinal que não é uma verificação (`FailsCheck`), como leitura
            vazia ou texto mal decodificado. Numa política sem verificação, tudo vai
            inteiro.
        layout: detector de regiões, como `PPDocLayout(drop=())`. Com ele, as
            linhas de cada página saem na ordem dos blocos que o detector
            achou, e dentro de cada bloco de cima para baixo. Um OCR por linha
            devolve as linhas pela altura, e numa folha em duas colunas isso
            intercala as colunas; a camada de texto de um PDF vem na ordem em
            que foi gravada, que pode ser qualquer uma. Cada linha vai ao bloco
            que contém o seu centro, ou ao mais próximo, e recebe o rótulo do
            bloco em `kind` quando o leitor não deu um. Vale para o que todo
            leitor leu, inclusive o caro. A detecção acontece na mesma
            renderização da leitura, uma vez por página; o tempo está em
            `docs/performance.md`. `None` mantém a ordem de cada leitor.
        trust_layer: o que fazer com a camada de texto de uma página
            `SEARCHABLE_SCAN`, que um OCR desconhecido deixou sob a imagem.
            `"visible"`, o padrão, não a lê como leitura: o leitor de pixels
            seguinte da cascata lê a página, e a camada entra como primeira
            família da releitura, antes de `confirm`, sem custo. Uma camada
            que discorda dos pixels sem deixar valor impossível nenhum sinal
            pega. `"always"` lê a camada
            como está, e só a evidência no texto a encaminha.
        entities: as verificações (`Check`) cujos valores saem em
            `Result.entities`, com estado e linha de origem. `None`, o
            padrão, usa as verificações da política e depois
            `DEFAULT_ENTITIES`: CPF, CNPJ, número CNJ, valor em reais, valor em
            moeda anterior ao real, data, data com dia da semana, data por
            extenso, folha, chave de acesso, linha digitável de boleto e
            código de arrecadação.
            Uma verificação aqui só extrai; para que ela também encaminhe a
            página, entra como `FailsCheck` na política.
        stamps: os formatos de tarja (`StampFormat`) procurados na camada
            de texto, para `Page.stamp`. `None`, o padrão, é
            `DEFAULT_STAMPS`, a tarja do e-SAJ; `[]` não procura nenhuma. Um
            nome vem de `STAMP_FORMATS`.
        folhas: as formas de folha (`Check` com o grupo `number`) procuradas
            nas linhas de elemento fixo, para `Page.folha`. `None` é `FOLHA`,
            `fls. N`; `[]` não procura nenhuma. Um nome vem de `FOLHA_FORMATS`.
        spans: `True` põe em cada `Entity.span` onde o valor está no texto
            das linhas dele. Desligado por omissão: o resultado fica do
            tamanho que tinha.
        allow_external: autoriza leitores que declaram `external = True`, isto
            é, que enviam a página para fora da máquina. Sem isto, pedir um
            deles levanta `ExternalBackendError` antes de o documento ser
            aberto. Vale para a cascata barata e para o backend caro.
        cache: cache de leituras, dos dois tiers e do detector de layout.
        dpi: DPI de renderização, para todas as páginas. Sem ele, uma
            página com raster é renderizada na resolução dele, presa ao
            intervalo de `MIN_NATIVE_DPI` a `MAX_NATIVE_DPI`, e uma sem raster
            em `DEFAULT_DPI`. Os três vivem em `docaudit.pdf`.
        pages: restringe o processamento a esses índices, zero-based. `None`
            processa o documento inteiro. As páginas de fora nem chegam a ser
            carregadas.
        min_raster_fraction: numa página nato-digital, a fração da página
            abaixo da qual um raster que nenhuma camada leu não vai ao leitor
            de pixels. `0.0`, o padrão, lê todos. O logotipo e o brasão do
            cabeçalho custam uma leitura de pixels que não traz linha útil;
            o valor que os separa de uma figura com texto não está calibrado,
            e depende do acervo. O raster fica em `Page.unread` e em
            `Result.figures()`, sem linha.
        workers: threads para o tier barato, e para o tier caro quando o
            leitor é hospedado (`external`). `1`, o padrão, não cria pool
            nenhum. Acima disso cada página barata vira uma tarefa, e as
            páginas de um leitor hospedado vão em paralelo. A saída é a
            mesma em qualquer número. Com que leitor isso rende, e por quê,
            está em `docs/performance.md`.

    Returns:
        O `Result` com os chunks lidos, as decisões de roteamento e o gasto.
        `decisions` é o veredito da política: com `strong=None` uma página pode
        estar em `STRONG` ali e mesmo assim ter sido lida só no barato, que é o
        modo de ensaio de uma política; `spent.pages_strong` conta o que rodou.
        Cada decisão traz em `steps` o que aconteceu com a página, na ordem.
        Uma página que o leitor caro recusou com `RuntimeError` entra em
        `pages_strong_failed` e emite um `RuntimeWarning`. Numa política que
        decide depois da leitura barata, como `evidence`, a página fica com
        a leitura barata. Numa que decide antes da leitura barata, como
        `all_strong`, não há leitura barata a que voltar: a página fica sem
        a leitura do corpo, e sai com `incomplete` quando não tem linha
        nenhuma. Um servidor
        ausente (`ConnectionError`) interrompe o processamento.
        Um leitor barato que falha numa página com `RuntimeError` dá a vez ao
        seguinte da cascata; a página entra em `pages_cheap_failed` e o aviso
        diz qual leitor falhou.
        Em `spent`, `pages_cheap` conta as páginas lidas pelo tier barato, o
        que inclui as escaladas quando a política precisa da leitura barata;
        `regions_cheap` conta as páginas em que o leitor seguinte da cascata
        leu, como região, os rasters que a camada de texto não leu;
        `regions_strong` conta as páginas em que o leitor caro leu só a região
        das linhas que falharam, e não a página.
        `pages_cheap_cached`, `pages_strong_cached`, `pages_confirm_cached` e
        `pages_layout_cached` contam o que veio do cache em cada etapa;
        `seconds_cheap`, `seconds_confirm` e `seconds_strong` são o tempo de
        parede de cada etapa, com a detecção de layout das páginas que ela
        renderizou. São relatados, e nada os limita.
    """
    if not 0.0 <= min_raster_fraction <= 1.0:
        raise ValueError(f"min_raster_fraction={min_raster_fraction!r} fora de [0, 1]")
    readers = [resolve(r, Reader, get_backend) for r in cheap]
    policy_obj = resolve(policy, TriagePolicy, get_policy)
    strong_backend = resolve(strong, Reader, get_backend) if strong is not None else None
    confirm_backend = resolve(confirm, Reader, get_backend) if confirm is not None else None
    if not allow_external:
        refuse_external([*readers, strong_backend, confirm_backend])
    doc_id = _pdf.doc_id_for(document)
    with _pdf.opened(document) as handle:
        return run_pipeline(
            handle,
            doc_id,
            facts=_pdf.facts_of(handle, file=document),
            policy=policy_obj,
            budget=budget if budget is not None else Budget(),
            readers=readers,
            strong=strong_backend,
            confirm=confirm_backend,
            reread=reread,
            layout=layout,
            trust_layer=trust_layer,
            entities=entities,
            stamps=stamps,
            folhas=folhas,
            spans=spans,
            cache=cache,
            dpi=dpi,
            min_raster_fraction=min_raster_fraction,
            workers=workers,
            pages=pages,
        )


def run_pipeline(
    handle: pdfium.PdfDocument,
    doc_id: str,
    *,
    policy: TriagePolicy,
    budget: Budget,
    readers: Sequence[Reader],
    strong: Reader | None,
    confirm: Reader | None,
    reread: Reread,
    layout: Layout | None,
    cache: ModelCallCache | None,
    dpi: int | None,
    workers: int,
    pages: Container[int] | None,
    classified: Sequence[Page] | None = None,
    trust_layer: TrustLayer = "visible",
    entities: Sequence[Check] | None = None,
    stamps: Sequence[StampFormat | str] | None = None,
    folhas: Sequence[Check | str] | None = None,
    spans: bool = False,
    facts: DocumentFacts | None = None,
    min_raster_fraction: float = 0.0,
) -> Result:
    """As etapas de `process` sobre um documento já aberto e leitores já resolvidos.

    É o que `process` chama depois de abrir o documento, e o que `Document`
    chama a cada leitura sem abri-lo de novo, passando em `classified` as
    páginas que já classificou e em `facts` o que o arquivo diz de si. Os
    argumentos são os de `process`, já resolvidos: ver lá o que cada um faz.
    """
    started = time.perf_counter()
    started_at = datetime.now(UTC)
    usage_before = _usage_of([*readers, strong, confirm])
    # As verificações da política: são elas que apontam a linha que falhou,
    # para a releitura por outra família e para a leitura cara por região.
    checks = list(policy.checks)
    entity_checks = _entity_checks(policy, entities)
    stamp_formats = _named(stamps, DEFAULT_STAMPS, STAMP_FORMATS)
    folha_checks = _named(folhas, (FOLHA,), FOLHA_FORMATS)
    for check in folha_checks:
        if "number" not in check.pattern.groupindex:
            raise ValueError(f"a folha {check.name!r} precisa do grupo `number`")

    run = _Run(handle, cache, dpi, layout, min_raster=min_raster_fraction)
    if classified is None:
        selected = _pdf.pages_of(handle, doc_id, dpi=dpi, only=pages)
    else:
        selected = [p for p in classified if pages is None or p.index in pages]
    if policy.needs_reads:
        # Guarda a renderização só da página que tem por onde escalar: leitura
        # vazia ou valores que falham até o mínimo da política. A escalada por
        # outro sinal renderiza a página de novo, e a conta continua a mesma.
        least = getattr(policy, "min_failures", 1)

        def may_escalate(page: Page, chunks: Sequence[Chunk]) -> bool:
            return not chunks or sum(len(c.failing(page, chunks)) for c in checks) >= least

        by_page = _cheap_stage(run, selected, readers, workers, trust_layer, may_escalate)
        decisions = list(policy.decide(selected, budget, by_page))
    else:
        by_page = {}
        decisions = list(policy.decide(selected, budget))
    _cap(decisions, budget.page_allowance(len(selected)))
    for d in decisions:
        run.steps[d.page].append(f"política: {d.reason}")
    by_index = {p.index: p for p in selected}
    # As falhas das verificações, uma vez por página encaminhada: a
    # releitura por outra família e a leitura cara por região as usam.
    failures = {
        d.page: _failures(checks, by_index[d.page], by_page.get(d.page, ()))
        for d in decisions
        if d.tier is Tier.STRONG
    }
    run.keep(failures)

    layer = TextLayerReader() if trust_layer == "visible" else None
    if (confirm is not None or layer is not None) and checks:
        with run.timed("seconds_confirm"):
            _confirm_stage(run, decisions, by_index, by_page, failures, checks, layer, confirm)

    tiers = {d.page: d.tier for d in decisions}
    escalated = [p for p in selected if tiers[p.index] is Tier.STRONG]
    run.keep({p.index for p in escalated})
    if not policy.needs_reads:
        # Sem leitor caro, nenhuma página escala e todas são lidas no barato.
        sent = {p.index for p in escalated} if strong is not None else set[int]()
        by_page = _cheap_stage(
            run, [p for p in selected if p.index not in sent], readers, workers, trust_layer
        )
    pages_cheap = len(by_page)
    with run.timed("seconds_strong"):
        by_decision = {d.page: d for d in decisions}
        deadline = started + budget.max_seconds if budget.max_seconds is not None else None
        deferred = _strong_stage(
            run,
            escalated,
            by_decision,
            by_page,
            failures,
            strong,
            checks,
            reread,
            workers,
            deadline,
        )
    # A página que o teto de tempo tirou do leitor caro numa política que
    # decide antes de ler ainda não tem leitura nenhuma: ela vai ao barato.
    unread_pages = [p for p in escalated if p.index in deferred and p.index not in by_page]
    if unread_pages:
        by_page.update(_cheap_stage(run, unread_pages, readers, workers, trust_layer))
        pages_cheap += len(unread_pages)
    run.views.clear()

    # A ordem de leitura vem por último, sobre o que ficou de todos os
    # leitores: a linha barata que o leitor caro não substituiu e a linha
    # cara entram no mesmo bloco.
    # A tarja e o carimbo de folha que o tribunal desenha à vista sobre a
    # digitalização são texto exato, mesmo quando a camada não é a leitura.
    for page in selected:
        lines, swapped = _with_visible_stamps(
            run,
            page,
            by_page.get(page.index, ()),
            stamp_formats,
            folha_checks,
            entity_checks,
            trust_layer,
        )
        if swapped or len(lines) != len(by_page.get(page.index, ())):
            by_page[page.index] = lines
            run.others.extend(swapped)
            run.steps[page.index].append(
                "camada à vista: tarja ou folha lida da camada, no lugar de "
                f"{len(swapped)} linha(s) dos pixels"
            )

    # A camada oculta da digitalização é outra família, já paga: a linha dela
    # com um id que confere e que os pixels não confirmaram entra no lugar.
    for page in selected:
        lines, swapped = _with_layer(
            run, page, by_page.get(page.index, ()), entity_checks, trust_layer
        )
        added = sum(1 for c in lines if c.source == TextLayerReader.name) - sum(
            1 for c in by_page.get(page.index, ()) if c.source == TextLayerReader.name
        )
        if added:
            by_page[page.index] = lines
            run.others.extend(swapped)
            run.steps[page.index].append(
                f"camada: {added} linha(s) com id que os pixels não confirmaram, "
                f"no lugar de {len(swapped)} linha(s) dos pixels"
            )

    # Os elementos fixos sobre o que ficou: são uma propriedade do documento
    # inteiro, e precisa das linhas finais de todas as páginas. A tarja e a
    # folha leem a ordem do arquivo, e por isso vêm antes da ordem do layout.
    by_page = mark_furniture(by_page)
    drawn = _draw_order_of(run, by_index)
    found_stamps = stamps_of(by_page, stamp_formats, drawn)
    page_folhas = _in_sequence(folhas_of(by_page, folha_checks, drawn))
    selected = [
        p.model_copy(update={"stamp": found_stamps.get(p.index), "folha": page_folhas.get(p.index)})
        for p in selected
    ]
    if layout is not None:
        for page in selected:
            regions = run.regions.get(page.index, [])
            by_page[page.index] = _order_by_layout(by_page.get(page.index, ()), regions)
            run.steps[page.index].append(
                f"layout: {len(regions)} bloco(s), linhas na ordem dos blocos"
            )

    # As discordâncias de valor com a camada oculta, sobre o texto final.
    for page in selected:
        run.others.extend(
            _amount_disagreements(run, page, by_page.get(page.index, ()), trust_layer)
        )
    # As entidades por último, sobre o texto final de cada página, na ordem
    # de leitura: o valor que o leitor caro trocou sai com a linha dele.
    final = {c.id for chunks in by_page.values() for c in chunks}
    # Só as leituras ao lado de uma linha que ficou: a linha que o leitor
    # caro substituiu já não está no resultado.
    others = [o for o in run.others if o.line in final]
    # A prova de erro do documento vem de outra família: a releitura por
    # `confirm` ou a camada oculta. A linha recusada do leitor caro fica em
    # `others` para quem revisa, e não prova nada.
    same_by_line: dict[str, list[OtherReading]] = {}
    for other in others:
        if other.same and (strong is None or other.reading.source != strong.name):
            same_by_line.setdefault(other.line, []).append(other)
    alike = {c.name: c.alike for c in entity_checks if c.alike is not None}
    found: list[Entity] = []
    for page in selected:
        lines = sorted(by_page.get(page.index, ()), key=reading_order_key)
        found.extend(
            _printed(e, page, lines, same_by_line, alike)
            for e in entities_of(entity_checks, page, lines, spans=spans)
        )

    usage_after = _usage_of([*readers, strong, confirm])
    chunks = tuple(c for p in selected for c in by_page.get(p.index, ()))
    # A página sem linha que só tem falhas é a que o leitor caro não leu e nenhum barato tentou.
    run.incomplete.update(
        p.index for p in selected if run.failures.get(p.index) and not by_page.get(p.index)
    )
    return Result(
        doc_id=doc_id,
        pages=tuple(selected),
        chunks=chunks,
        decisions=tuple(
            d.model_copy(
                update={
                    "steps": tuple(run.steps[d.page]),
                    "seconds": dict(run.seconds.get(d.page, {})),
                    "failures": tuple(run.failures.get(d.page, ())),
                    "incomplete": d.page in run.incomplete,
                }
            )
            for d in decisions
        ),
        entities=tuple(found),
        others=tuple(others),
        spent=_spent(run, len(selected), pages_cheap, started, usage_before, usage_after),
        run=Run(
            started_at=started_at,
            policy=policy.name,
            budget=budget,
            cheap=tuple(r.name for r in readers),
            confirm=confirm.name if confirm is not None else None,
            strong=strong.name if strong is not None else None,
            reread=reread,
            trust_layer=trust_layer,
            dpi=dpi,
            entities=tuple(c.name for c in entity_checks),
            stamps=tuple(f.name for f in stamp_formats),
            folhas=tuple(c.name for c in folha_checks),
            spans=spans,
            min_raster_fraction=min_raster_fraction,
            versions=_versions(
                [*readers, layer, confirm, strong],
                {c.source for c in (*chunks, *(o.reading for o in others))},
                layout if run.regions else None,
            ),
        ),
        document=facts,
        library_version=_library_version(),
    )


def _versions(
    readers: Sequence[Reader | None], sources: Container[str], layout: Layout | None
) -> dict[str, str]:
    """O `output_version` de cada leitor que leu alguma linha do resultado, e o do detector.

    Só de quem leu: a versão de um leitor hospedado sem `served=` pergunta ao
    servidor, e um leitor caro que nunca foi chamado não deve custar essa
    pergunta. Dois leitores de mesmo nome em papéis diferentes, como dois
    `PPOCR` em motores diferentes, não se distinguem pela linha; fica a
    versão do primeiro, na ordem cascata, camada, releitura, caro.
    """
    out: dict[str, str] = {}
    for reader in readers:
        if reader is not None and reader.name in sources and reader.name not in out:
            out[reader.name] = reader.output_version
    if layout is not None:
        out["layout"] = layout.output_version
    return out


def _spent(
    run: _Run,
    pages_total: int,
    pages_cheap: int,
    started: float,
    usage_before: Mapping[str, float],
    usage_after: Mapping[str, float],
) -> Spent:
    """O gasto da execução: os contadores das etapas e a diferença do que os leitores contaram."""
    c = run.spent
    usage = {k: v - usage_before.get(k, 0.0) for k, v in usage_after.items()}
    return Spent(
        pages_total=pages_total,
        pages_cheap=pages_cheap,
        pages_strong=int(c["pages_strong"]),
        pages_cheap_cached=int(c["pages_cheap_cached"]),
        pages_cheap_failed=int(c["pages_cheap_failed"]),
        regions_cheap=int(c["regions_cheap"]),
        regions_strong=int(c["regions_strong"]),
        lines_strong_rejected=int(c["lines_strong_rejected"]),
        pages_strong_cached=int(c["pages_strong_cached"]),
        pages_strong_failed=int(c["pages_strong_failed"]),
        pages_confirmed=int(c["pages_confirmed"]),
        pages_confirmed_same=int(c["pages_confirmed_same"]),
        pages_confirmed_fixed=int(c["pages_confirmed_fixed"]),
        pages_confirm_cached=int(c["pages_confirm_cached"]),
        pages_layout_cached=int(c["pages_layout_cached"]),
        seconds_cheap=c["seconds_cheap"],
        seconds_confirm=c["seconds_confirm"],
        seconds_strong=c["seconds_strong"],
        seconds=time.perf_counter() - started,
        calls=usage.get("calls"),
        tokens_in=usage.get("tokens_in"),
        tokens_out=usage.get("tokens_out"),
        usd=usage.get("usd"),
    )


def _cap(decisions: list[RoutingDecision], allowance: int | None) -> None:
    """Deixa em `STRONG` só as primeiras `allowance` decisões; o resto volta a `CHEAP`, no lugar.

    A política escolhe quais páginas escalar e em que ordem; o teto vale
    para qualquer política, e é aplicado na ordem em que ela devolveu as
    decisões.
    """
    if allowance is None:
        return
    kept = 0
    for k, decision in enumerate(decisions):
        if decision.tier is not Tier.STRONG:
            continue
        if kept < allowance:
            kept += 1
            continue
        decisions[k] = decision.model_copy(
            update={
                "tier": Tier.CHEAP,
                "reason": f"{decision.reason}; fora do teto de {allowance} página(s)",
            }
        )


def _library_version() -> str:
    # Import local: docaudit/__init__.py importa `process`, então um import de
    # módulo aqui seria circular.
    from docaudit import __version__

    return __version__
