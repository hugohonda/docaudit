# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Um documento aberto, para um agente ler e voltar a pontos dele.

`process` lê um documento de uma vez e devolve o resultado. Quem lê por
tarefa, um agente que extrai valores ou confere partes, precisa de mais três
coisas: saber quais linhas não merecem confiança e onde estão, pedir uma
releitura de um só recorte quando a tarefa precisa daquele valor, e ver o
recorte ou a página. `Document` guarda o documento aberto, os leitores e o cache entre
essas chamadas, para que nada seja aberto ou carregado duas vezes.
"""

from __future__ import annotations

from collections.abc import Container, Sequence
from contextlib import ExitStack
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict

from docaudit import pdf as _pdf
from docaudit.pdf import PageView
from docaudit.policies import (
    DEFAULT_SIGNALS,
    Check,
    LineSignal,
    StampFormat,
    get_policy,
)
from docaudit.process import (
    DEFAULT_CASCADE,
    Reread,
    TrustLayer,
    read_region,
    refuse_external,
    resolve,
    run_pipeline,
)
from docaudit.registry import get_backend
from docaudit.types import (
    BBox,
    Budget,
    Chunk,
    Layout,
    OtherReading,
    Reader,
    Result,
    TriagePolicy,
)

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType

    import pypdfium2 as pdfium

    from docaudit.cache import ModelCallCache

__all__ = ["Document", "Doubt"]


def _line_signals(signals: Sequence[object]) -> list[LineSignal]:
    """Os sinais de `signals` que apontam linha."""
    return [s for s in signals if isinstance(s, LineSignal)]


class Doubt(BaseModel):
    """Uma linha lida que merece revisão: o que falhou, o valor e a linha.

    `check` é o nome do campo cujo valor falha ou que outra família lê
    diferente, ou o nome do sinal de texto mal decodificado; `value` é o
    valor como lido, ou os pontos de código.
    `others` são as leituras de outro leitor no mesmo lugar, que não
    substituíram a linha: vazio quando ninguém a releu.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk: Chunk
    check: str
    value: str
    others: tuple[OtherReading, ...] = ()


class Document:
    """Um documento aberto, com leitores e cache fixos, para ler e reler sob demanda.

    ```python
    with Document("autos.pdf", strong=PPOCR()) as doc:
        result = doc.read(budget=Budget(max_strong_pages=5))
        for doubt in doc.doubts(result):
            better = doc.reread(doubt.chunk.page, doubt.chunk.bbox, "ppocr")
    ```

    Os leitores e a política são resolvidos uma vez. Um leitor que sai da
    máquina é recusado aqui, antes de qualquer leitura, a não ser com
    `allow_external=True`.
    """

    def __init__(
        self,
        document: Path | str | bytes,
        *,
        cheap: Sequence[Reader | str] = DEFAULT_CASCADE,
        strong: Reader | str | None = None,
        confirm: Reader | str | None = None,
        layout: Layout | None = None,
        trust_layer: TrustLayer = "visible",
        cache: ModelCallCache | None = None,
        dpi: int | None = None,
        allow_external: bool = False,
    ) -> None:
        """Abre o documento e resolve os leitores; os argumentos são os de `process`."""
        self.doc_id = _pdf.doc_id_for(document)
        self.readers = [resolve(r, Reader, get_backend) for r in cheap]
        self.strong = resolve(strong, Reader, get_backend) if strong is not None else None
        self.confirm = resolve(confirm, Reader, get_backend) if confirm is not None else None
        self.layout = layout
        self.trust_layer: TrustLayer = trust_layer
        self.cache = cache
        self.dpi = dpi
        self.allow_external = allow_external
        if not allow_external:
            refuse_external([*self.readers, self.strong, self.confirm])
        with ExitStack() as stack:
            self._handle = stack.enter_context(_pdf.opened(document))
            self._pages = {p.index: p for p in _pdf.pages_of(self._handle, self.doc_id, dpi=dpi)}
            self.facts = _pdf.facts_of(self._handle, file=document)
            """O que o arquivo diz de si; o mesmo que `Result.document` de cada leitura."""
            # Só depois de classificar: se algo falha antes, o `with` fecha o documento.
            self._closing = stack.pop_all()
        self._closed = False
        self.signals: Sequence[LineSignal] = _line_signals(DEFAULT_SIGNALS)
        """Os sinais de `doubts`, os que apontam linha: os da última política lida, ou os padrão."""

    def __enter__(self) -> Self:
        """Permite `with Document(...) as doc`."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Fecha o documento ao sair do `with`."""
        self.close()

    def close(self) -> None:
        """Fecha o documento. As leituras feitas continuam válidas; fechar de novo não faz nada."""
        if not self._closed:
            self._closed = True
            self._closing.close()

    def _open_handle(self) -> pdfium.PdfDocument:
        if self._closed:
            raise ValueError("documento fechado")
        return self._handle

    def _view(self, page: int) -> PageView:
        handle = self._open_handle()
        if page not in self._pages:
            last = len(self._pages) - 1
            raise IndexError(f"página {page} fora do documento: índices de 0 a {last}")
        return PageView(handle, self._pages[page], dpi=self.dpi)

    def read(
        self,
        *,
        policy: TriagePolicy | str = "evidence",
        budget: Budget | None = None,
        reread: Reread = "page",
        workers: int = 1,
        pages: Container[int] | None = None,
        entities: Sequence[Check] | None = None,
        stamps: Sequence[StampFormat | str] | None = None,
        folhas: Sequence[Check | str] | None = None,
        spans: bool = False,
    ) -> Result:
        """Lê o documento como `process`, sem abri-lo nem classificá-lo de novo.

        O padrão é a política `evidence`: um agente quer saber o que falhou.
        Os sinais da política que apontam linha passam a ser os de `doubts`.
        `entities`, `stamps`, `folhas` e `spans` são os de `process`.
        """
        # `furniture` é visto sobre as páginas lidas nesta chamada: com `pages`,
        # uma linha repetida só noutras páginas sai sem marca.
        policy_obj = resolve(policy, TriagePolicy, get_policy)
        self.signals = _line_signals(policy_obj.signals) or self.signals
        return run_pipeline(
            self._open_handle(),
            self.doc_id,
            policy=policy_obj,
            budget=budget if budget is not None else Budget(),
            readers=self.readers,
            strong=self.strong,
            confirm=self.confirm,
            reread=reread,
            layout=self.layout,
            trust_layer=self.trust_layer,
            cache=self.cache,
            dpi=self.dpi,
            workers=workers,
            pages=pages,
            classified=list(self._pages.values()),
            entities=entities,
            stamps=stamps,
            folhas=folhas,
            spans=spans,
            facts=self.facts,
        )

    def doubts(self, result: Result, signals: Sequence[LineSignal] | None = None) -> list[Doubt]:
        """As linhas de `result` que um sinal aponta, com a caixa de cada uma.

        O valor que falha uma verificação, só em linha escrita por máquina,
        porque numa página composta o erro é do documento; e a linha com
        caractere de decodificação quebrada, em qualquer texto, com os pontos
        de código em `value`. Na linha que nenhum sinal aponta, a leitura ao
        lado com `check` vira dúvida desse campo. Uma página encaminhada por leitura vazia não
        aponta linha, e aparece em `result.decisions`, não aqui. `signals` são
        os sinais a aplicar; sem eles, os de `signals` do documento.
        """
        pages = {p.index: p for p in result.pages}
        others: dict[str, list[OtherReading]] = {}
        for other in result.others:
            if not other.replaced:
                others.setdefault(other.line, []).append(other)
        doubts = [
            Doubt(
                chunk=chunk,
                check=signal.field,
                value=value,
                others=tuple(others.get(chunk.id, ())),
            )
            for index, chunks in result.by_page().items()
            for signal in (signals if signals is not None else self.signals)
            for value, chunk in signal.failing(pages[index], chunks)
        ]
        # Na linha que nenhum sinal aponta, a dúvida vem do outro leitor que leu
        # outro valor, a camada de OCR ou a linha recusada do leitor caro: a
        # leitura ao lado traz o campo e o valor que contradiz.
        doubted = {d.chunk.id for d in doubts}
        lines = {c.id: c for c in result.chunks}
        doubts.extend(
            Doubt(chunk=lines[o.line], check=o.check, value=o.value, others=(o,))
            for o in result.others
            if o.line not in doubted and o.check is not None and o.value is not None
        )
        return doubts

    def reread(self, page: int, box: BBox, reader: Reader | str) -> list[Chunk]:
        """Lê só o recorte `box` da página com `reader`; as linhas voltam em coordenadas da página.

        Não mexe em nenhum `Result`: quem chama decide o que fazer com a
        releitura. O recorte entra no cache com a caixa na chave.
        """
        backend = resolve(reader, Reader, get_backend)
        if not self.allow_external:
            refuse_external([backend])
        chunks, _ = read_region(self._view(page), box, backend, self.cache)
        return chunks

    def crop(self, page: int, box: BBox, *, grayscale: bool = True) -> bytes:
        """O PNG do recorte `box` da página, na resolução em que os leitores a viram."""
        return self._view(page).region(box).image(grayscale=grayscale)

    def render(self, page: int, *, grayscale: bool = True) -> bytes:
        """O PNG da página inteira, na resolução em que os leitores a viram.

        Sai direto da renderização, sem o recorte: `crop` com a caixa da página
        toda decodifica o PNG e o codifica de novo. As caixas de um `Chunk`,
        normalizadas, caem nesta imagem como caem na que o leitor leu.
        """
        return self._view(page).image(grayscale=grayscale)
