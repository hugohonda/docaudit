# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Leitor sobre o modelo de leitura do Azure AI Document Intelligence, pela API REST.

Fala só com a biblioteca padrão. O serviço roda fora da máquina: o leitor é
sempre `external`, e `process()` exige `allow_external=True`. A imagem da
página, ou do recorte, sai da máquina a cada leitura; ver `docs/security.md`.

A página vai como PNG, e não como PDF: o serviço lê os pixels que a
biblioteca renderizou, sem depender da camada de texto do arquivo. A leitura
é assíncrona. O pedido devolve o endereço da operação, e o leitor o consulta
até ela terminar.

O serviço devolve uma linha por linha de texto, com o polígono dela na imagem
enviada, e a confiança de cada palavra. O leitor devolve um chunk por linha:
a caixa é a envoltória do polígono, e a confiança é a menor entre as palavras
da linha, porque a linha é tão certa quanto a palavra mais duvidosa dela.

O serviço lê sozinho a página girada, e o polígono de cada linha segue o
sentido em que ela é lida. O leitor leva esse sentido a `Chunk.turn`,
arredondado ao quarto de volta, e a caixa segue no sistema da imagem. O giro
é da linha: na folha de cabeça para baixo, o carimbo aposto em pé sai com
`0`. A linha escrita de través na página, que é a tarja da margem, fica com
o giro da página.

O leitor conta o que gastou em `usage`: uma chamada por página ou recorte
enviado, e dólares quando `price_per_page` foi declarado. Uma leitura servida
pelo cache não passa por aqui e não conta.

Um 429 ou 5xx, o tempo esgotado e a conexão caída são repetidos `retries`
vezes. Esgotadas as tentativas, ou quando o serviço diz que a operação falhou,
o leitor levanta `RuntimeError`: a página falha, e o documento segue. A
credencial recusada (401 ou 403) não é desta página: levanta
`PermissionError`, que interrompe o documento.
"""

from __future__ import annotations

import bisect
import io
import json
import math
import threading
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, cast

from docaudit.backends.vlm import (
    _seconds,  # pyright: ignore[reportPrivateUsage] - o mesmo Retry-After do leitor `vlm`
    _TransientError,  # pyright: ignore[reportPrivateUsage] - a mesma falha passageira
)
from docaudit.types import BBox, Chunk

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from email.message import Message

    from PIL import Image

    from docaudit.pdf import PageView
    from docaudit.types import Page, Turn

__all__ = ["AzureRead"]

_MIN_SIDE = 50
"""O menor lado, em pixels, que o serviço aceita numa imagem."""
_MAX_SIDE = 10_000
"""O maior lado, em pixels, que o serviço aceita numa imagem."""
_WHOLE = BBox(x0=0.0, y0=0.0, x1=1.0, y1=1.0)
"""A caixa da página inteira: a vista com ela é a página, girada ou não."""
_POLL = 2.0
"""Segundos entre duas consultas à operação, quando o serviço não diz a espera.

O serviço pede que a operação não seja consultada mais de uma vez a cada dois
segundos.
"""


def _quarter(angle: float) -> Turn:
    """O giro, em quartos de volta, de um texto girado `angle` graus no sentido horário.

    Para ler a linha em pé, a página gira o mesmo tanto no sentido
    anti-horário, que é o sentido de `Chunk.turn`. A inclinação pequena de uma
    folha torta arredonda para zero.
    """
    return cast("Turn", round(angle / 90.0) % 4 * 90)


def _turn_of(polygon: Sequence[float], page_turn: Turn) -> Turn:
    """O giro de uma linha, pelo sentido em que o polígono dela é lido.

    O serviço dá os pontos a partir do canto de cima à esquerda do texto como
    ele é lido: do primeiro ao segundo ponto vai o sentido da leitura. Na
    imagem, o eixo vertical cresce para baixo, e o ângulo desse sentido já é
    medido no sentido horário. A linha de través na página fica com o giro da
    página: é a tarja da margem, que a página em pé tem na vertical.
    """
    along = math.degrees(math.atan2(polygon[3] - polygon[1], polygon[2] - polygon[0]))
    turn = _quarter(along)
    return page_turn if (turn - page_turn) % 180 else turn


def _sendable(pixels: Image.Image, png: bytes) -> bytes:
    """O PNG que o serviço aceita: o mesmo, ou a imagem pequena sobre um fundo branco.

    O recorte de uma linha tem menos altura que o mínimo do serviço. Ele vai
    no canto de cima à esquerda de um fundo branco, e as caixas seguem
    medidas pelo recorte.
    """
    width, height = pixels.size
    if max(width, height) > _MAX_SIDE:
        raise RuntimeError(
            f"a imagem tem {width}x{height} pixels, e o Azure aceita até {_MAX_SIDE} de lado"
        )
    if min(width, height) >= _MIN_SIDE:
        return png
    from PIL import Image

    padded = Image.new("RGB", (max(width, _MIN_SIDE), max(height, _MIN_SIDE)), "white")
    padded.paste(pixels, (0, 0))
    buffer = io.BytesIO()
    padded.save(buffer, format="PNG")
    return buffer.getvalue()


class AzureRead:
    """Lê uma página pelo modelo de leitura do Azure AI Document Intelligence."""

    name = "azure-read"
    external = True

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        *,
        model: str = "prebuilt-read",
        api_version: str = "2024-11-30",
        price_per_page: float | None = None,
        timeout: float = 120.0,
        retries: int = 3,
        on_result: Callable[[PageView, Mapping[str, object]], None] | None = None,
    ) -> None:
        """Aponta para o recurso do Azure. Nada é enviado até a primeira leitura.

        Args:
            endpoint: o endereço do recurso, como
                `https://<recurso>.cognitiveservices.azure.com`.
            api_key: a chave do recurso, enviada em `Ocp-Apim-Subscription-Key`.
            model: o modelo de análise. Entra em `output_version`.
            api_version: a versão da API. Entra em `output_version`: outra
                versão pode ler de outro jeito.
            price_per_page: dólares por página lida, para que `usage["usd"]`
                tenha valor. A biblioteca não traz tabela de preços: o número
                é de quem chama, e envelhece. O serviço cobra por imagem
                enviada, e um recorte conta como uma página.
            timeout: segundos por pedido, e também o tempo que a operação
                tem para terminar depois de aceita.
            retries: quantas vezes repetir um pedido que o serviço recusou
                por carga (HTTP 429 ou 5xx), que esgotou o `timeout` ou cuja
                conexão caiu, antes de a página falhar. A espera segue o
                `Retry-After` do serviço, ou dobra a partir de um segundo.
            on_result: chamado com a vista e o `analyzeResult` de cada página
                inteira que o serviço leu, antes de as linhas serem montadas.
                Serve a quem guarda o resultado do serviço para não pagar a
                mesma página duas vezes; `lines_of` monta as linhas de um
                resultado guardado. A leitura de um recorte não o chama: o
                resultado dela não é o da página. `view.turn` diz o giro em
                que a página foi enviada, e as medidas da imagem estão no
                próprio resultado. Com `workers` > 1, a chamada vem de várias
                threads. A exceção que ele levanta falha a página.

        Raises:
            ValueError: `endpoint` ou `api_key` vazio, ou `retries` negativo.
        """
        if not endpoint or not api_key:
            raise ValueError("endpoint e api_key são obrigatórios")
        if retries < 0:
            raise ValueError("retries não pode ser negativo")
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.api_version = api_version
        self.price_per_page = price_per_page
        self.timeout = timeout
        self.retries = retries
        self.on_result = on_result
        self.output_version = f"1:{model}:{api_version}"
        self.usage: dict[str, float] = {"calls": 0.0}
        if price_per_page is not None:
            self.usage["usd"] = 0.0
        # Com `workers` > 1, `process()` chama o leitor externo de várias threads.
        self._counting = threading.Lock()

    def read(self, view: PageView) -> Sequence[Chunk]:
        """Um chunk por linha que o serviço leu, na ordem em que ele as devolve."""
        # A imagem é renderizada no thread chamador: o pdfium não é seguro entre threads.
        pixels = view.pixels(grayscale=False)
        # Numa folha de uma cor só não há o que ler, e a chamada seria cobrada.
        if pixels.getcolors(1) is not None:
            return []
        result = self._analyze(_sendable(pixels, view.image(grayscale=False)))
        if self.on_result is not None and view.box in (None, _WHOLE):
            self.on_result(view, result)
        return _lines(view.page, result, pixels.size, self.name)

    def lines_of(
        self, view: PageView, result: Mapping[str, object], *, turn: Turn = 0
    ) -> list[Chunk]:
        """As linhas de um `analyzeResult` guardado, como `read` as devolveria para `view`.

        `result` é o que `on_result` recebeu para a página inteira, e `turn`
        o giro da vista daquela leitura. A página pode chegar agora em outro
        giro, porque a leitura barata a leu de outro jeito: as caixas e o
        giro de cada linha são levados ao sistema de `view`. Nada é enviado
        ao serviço, e `usage` não conta.
        """
        first = _obj(next(iter(_items(result.get("pages"))), None))
        size = (int(_number(first.get("width"), 1.0)), int(_number(first.get("height"), 1.0)))
        lines = _lines(view.page, dict(result), size, self.name)
        if turn == view.turn:
            return lines
        back = (360 - view.turn) % 360
        return [
            Chunk.make(
                view.page,
                line.bbox.unturned(turn).unturned(back),
                line.source,
                line.text,
                confidence=line.confidence,
                reading_order=line.reading_order,
                turn=_quarter(float(turn + line.turn + back)),
            )
            for line in lines
        ]

    def _analyze(self, png: bytes) -> dict[str, object]:
        """Envia a imagem e espera a operação: o `analyzeResult`, ou a falha da página."""
        url = (
            f"{self.endpoint}/documentintelligence/documentModels/{self.model}:analyze"
            f"?api-version={self.api_version}"
        )
        headers, _ = self._request(
            urllib.request.Request(url, data=png, headers=self._headers("image/png"))
        )
        self._count()
        operation = headers.get("Operation-Location")
        if not operation:
            raise RuntimeError("o Azure aceitou o pedido sem dizer onde está a operação")
        deadline = time.monotonic() + self.timeout
        wait = _seconds(headers.get("Retry-After"))
        while True:
            time.sleep(wait if wait is not None else _POLL)
            headers, state = self._request(
                urllib.request.Request(operation, headers=self._headers())
            )
            status = state.get("status")
            if status == "succeeded":
                result = _obj(state.get("analyzeResult"))
                if not result:
                    raise RuntimeError(f"o Azure terminou sem resultado: {str(state)[:300]}")
                return result
            if status in ("failed", "canceled"):
                raise RuntimeError(f"o Azure não leu a página ({status}): {_error_of(state)}")
            if time.monotonic() > deadline:
                raise RuntimeError(f"o Azure não terminou a leitura em {self.timeout:.0f} s")
            wait = _seconds(headers.get("Retry-After"))

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {"Ocp-Apim-Subscription-Key": self.api_key}
        if content_type is not None:
            headers["Content-Type"] = content_type
        return headers

    def _count(self) -> None:
        """Soma uma página enviada ao contador do leitor, sob a trava."""
        with self._counting:
            self.usage["calls"] += 1
            if self.price_per_page is not None:
                self.usage["usd"] += self.price_per_page

    def _request(self, request: urllib.request.Request) -> tuple[Message, dict[str, object]]:
        """Os cabeçalhos e o corpo da resposta; a falha passageira é repetida `retries` vezes."""
        for attempt in range(self.retries):
            try:
                return self._send(request)
            except _TransientError as exc:
                time.sleep(exc.wait if exc.wait is not None else float(2**attempt))
        return self._send(request)

    def _send(self, request: urllib.request.Request) -> tuple[Message, dict[str, object]]:
        """Um pedido ao serviço: os cabeçalhos e o corpo, ou a falha classificada."""
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                headers = cast("Message", resp.headers)
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            retry_after = exc.headers.get("Retry-After")
            exc.close()
            message = f"o Azure respondeu {exc.code}: {detail}"
            if exc.code in (401, 403):
                raise PermissionError(message) from exc
            if exc.code == 429 or exc.code >= 500:
                raise _TransientError(message, _seconds(retry_after)) from exc
            raise RuntimeError(message) from exc
        except OSError as exc:
            # A conexão recusada, a que caiu e o tempo esgotado: o serviço é de fora
            # da máquina, e outra tentativa pode resolver.
            raise _TransientError(f"o Azure não respondeu: {exc!r}") from exc
        if not raw.strip():
            return headers, {}
        try:
            data: object = json.loads(raw)
        except ValueError as exc:
            raise RuntimeError(f"a resposta do Azure não pôde ser lida: {exc!r}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"a resposta do Azure não é um objeto JSON: {str(data)[:300]}")
        return headers, cast("dict[str, object]", data)


def _obj(value: object) -> dict[str, object]:
    """O valor como objeto JSON; vazio quando não é um."""
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def _items(value: object) -> list[object]:
    """O valor como lista JSON; vazia quando não é uma."""
    return cast("list[object]", value) if isinstance(value, list) else []


def _number(value: object, default: float = 0.0) -> float:
    """O valor como número; `default` quando não é um."""
    return float(value) if isinstance(value, int | float) else default


def _error_of(state: dict[str, object]) -> str:
    """O código e a mensagem do erro de uma operação que falhou."""
    error = _obj(state.get("error"))
    return f"{error.get('code')}: {error.get('message')}" if error else str(state)[:300]


def _lines(
    page: Page, result: dict[str, object], size: tuple[int, int], source: str
) -> list[Chunk]:
    """Um chunk por linha do resultado, com a caixa normalizada pela imagem de `size`.

    O serviço mede o polígono na unidade da página que ele devolve. A caixa é
    a envoltória do polígono, na imagem como ela chegou à biblioteca. A imagem
    pequena que foi enviada sobre um fundo branco tem as caixas medidas pelo
    recorte, e não pelo fundo.
    """
    pages = _items(result.get("pages"))
    if not pages:
        return []
    first = _obj(pages[0])
    width, height = size
    # A página do serviço é a imagem enviada, que tem ao menos `_MIN_SIDE` de lado. A
    # caixa é medida no recorte: a largura dele na unidade do serviço é esta.
    width_in_unit = width * _number(first.get("width"), 1.0) / max(width, _MIN_SIDE)
    height_in_unit = height * _number(first.get("height"), 1.0) / max(height, _MIN_SIDE)
    page_turn = _quarter(_number(first.get("angle")))
    # As palavras vêm na ordem do texto: a posição de cada uma e a confiança dela.
    words = sorted(
        (int(_number(_obj(word.get("span")).get("offset"), -1.0)), _number(word["confidence"]))
        for word in map(_obj, _items(first.get("words")))
        if isinstance(word.get("confidence"), int | float)
    )
    starts = [start for start, _ in words]
    chunks: list[Chunk] = []
    for line in map(_obj, _items(first.get("lines"))):
        text = str(line.get("content") or "").strip()
        polygon = [_number(v) for v in _items(line.get("polygon"))]
        if not text or len(polygon) < 8:
            continue
        xs, ys = polygon[0::2], polygon[1::2]
        box = BBox.from_pixels(
            min(xs), min(ys), max(xs), max(ys), width_px=width_in_unit, height_px=height_in_unit
        )
        if box.x1 <= box.x0 or box.y1 <= box.y0:
            continue
        # A confiança da linha é a menor entre as palavras que começam num trecho dela.
        found = [
            confidence
            for span in map(_obj, _items(line.get("spans")))
            for _, confidence in words[
                bisect.bisect_left(starts, int(_number(span.get("offset")))) : bisect.bisect_left(
                    starts, int(_number(span.get("offset")) + _number(span.get("length")))
                )
            ]
        ]
        chunks.append(
            Chunk.make(
                page,
                box,
                source,
                text,
                confidence=min(max(min(found), 0.0), 1.0) if found else None,
                reading_order=len(chunks),
                turn=_turn_of(polygon, page_turn),
            )
        )
    return chunks
