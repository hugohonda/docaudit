# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Leitor sobre um modelo de visão e linguagem, por uma API compatível com a da OpenAI.

Fala só com a biblioteca padrão. Serve a dois casos, com a mesma classe:

- um `llama-server` na própria máquina, com um modelo de OCR em GGUF. Os
  presets são `glm-ocr` (GLM-OCR, 0,9B, MIT), o padrão, e `paddleocr-vl`
  (PaddleOCR-VL-1.6, 0,9B, Apache-2.0), os dois treinados sobre recortes de região,
  não sobre a folha inteira;
- um modelo hospedado, por qualquer endpoint que aceite o formato de chat da
  OpenAI com imagem embutida: o da própria OpenAI, o compatível do Gemini, o
  da Anthropic, o OpenRouter. O preset é `generic`, com um prompt de
  transcrição em português, e `served` nomeia o modelo no pedido. Um host que
  não seja a própria máquina torna o leitor `external`, e `process()` passa a
  exigir `allow_external=True`.

Com um `PPDocLayout`, o leitor recorta a página por região, manda cada recorte
com o prompt do tipo dela e devolve um chunk por região, com a caixa da região e
a ordem de leitura do layout. Sem detector, manda a página inteira e devolve um
chunk por página, com a caixa cobrindo a folha: é o modo em que os modelos de
OCR alucinam mais, e fica para quem não quer o detector ou usa um modelo
treinado sobre a folha.

O leitor conta o que gastou em `usage`: chamadas, tokens de entrada e de
saída, e dólares quando `prices` foi declarado. `process()` soma o gasto em
`Result.spent`. Uma leitura servida pelo cache não passa por aqui e não conta.

O `llama-server` analisa a saída do modelo antes de devolvê-la, e numa fração
das chamadas rejeita o próprio texto com um erro 500. Um 429 ou 5xx, o
tempo esgotado e a conexão caída são repetidos `retries` vezes, num servidor
local também; com `retries=0`, o padrão, nenhum é repetido. Esgotadas as
tentativas, o leitor levanta `RuntimeError` com o código e o corpo, e a página
inteira falha; o documento segue. Uma resposta que não se lê também falha a
página. A conexão recusada é o único caso que difere: num servidor local, é o
servidor ausente, que levanta `ConnectionError` e interrompe o documento; num
servidor fora da máquina, é mais uma falha a repetir.

Servidores e pesos: ver `docs/how-to/vlm.md`.
"""

from __future__ import annotations

import base64
import io
import json
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Literal, cast
from urllib.parse import urlparse

from docaudit.types import BBox, Chunk

if TYPE_CHECKING:
    from collections.abc import Sequence

    from PIL import Image

    from docaudit.pdf import PageView
    from docaudit.types import Layout, Page, Region

__all__ = ["DEFAULT_URL", "PRESETS", "VLM"]

DEFAULT_URL = "http://127.0.0.1:8089"
"""Onde o `llama-server` local atende por padrão."""
Model = Literal["glm-ocr", "paddleocr-vl", "generic"]

_GENERIC_TEXT = (
    "Transcreva todo o texto desta imagem, na ordem de leitura, exatamente como está "
    "impresso: sem traduzir, sem corrigir, sem resumir e sem comentar. Preserve as quebras "
    "de linha. Uma tabela sai uma linha por linha da tabela, com as células separadas "
    "por ' | '. Se não houver texto, responda com uma linha vazia."
)
_GENERIC_TABLE = (
    "Transcreva esta tabela, uma linha de texto por linha da tabela, com as células "
    "separadas por ' | ', exatamente como está impresso: sem corrigir nem completar. "
    "Se não houver tabela, transcreva o texto que houver."
)

PRESETS: dict[Model, dict[str, str]] = {
    "glm-ocr": {"text": "Text Recognition:", "table": "Table Recognition:"},
    "paddleocr-vl": {"text": "OCR:", "table": "Table Recognition:"},
    "generic": {"text": _GENERIC_TEXT, "table": _GENERIC_TABLE},
}
"""O prompt por tipo de região: o que cada modelo de OCR espera, e um genérico."""

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_FULL_PAGE = BBox(x0=0.0, y0=0.0, x1=1.0, y1=1.0)
_LATIN_OR_DIGIT = re.compile(r"[A-Za-zÀ-ɏ0-9]")
_ROW_END = re.compile(r"<nl>|</tr>", re.IGNORECASE)
_CELL_END = re.compile(r"<[a-z]cel>|</t[dh]>", re.IGNORECASE)
_TABLE_TAG = re.compile(r"</?(?:table|thead|tbody|tr|td|th|html|body)[^>]*>", re.IGNORECASE)


def _rows(text: str) -> str:
    """A marcação de tabela dos modelos vira linhas de células separadas por ` | `.

    O GLM-OCR devolve HTML; o PaddleOCR-VL devolve células como `<fcel>` e
    quebras como `<nl>`. Nos dois casos uma linha da tabela vira uma linha de
    texto, para que nome e valor sigam na mesma linha.
    """
    text = _ROW_END.sub("\n", text)
    text = _CELL_END.sub(" | ", text)
    return _TABLE_TAG.sub("", text)


def _clean(text: str) -> str:
    """Linhas com ao menos uma letra latina ou dígito.

    Numa página sem texto o modelo repete uma frase em outro alfabeto.
    """
    return "\n".join(
        line.strip() for line in text.splitlines() if _LATIN_OR_DIGIT.search(line)
    ).strip()


class VLM:
    """Lê uma página por um modelo de visão e linguagem, por região ou inteira."""

    name = "vlm"

    def __init__(
        self,
        url: str = DEFAULT_URL,
        model: Model = "glm-ocr",
        *,
        served: str | None = None,
        api_key: str | None = None,
        prices: tuple[float, float] | None = None,
        layout: Layout | None = None,
        concurrency: int = 1,
        timeout: float = 600.0,
        max_tokens: int = 4096,
        reasoning: str | None = None,
        retries: int = 0,
    ) -> None:
        """Aponta para um servidor e escolhe o preset.

        Args:
            url: base do servidor, até antes de `/v1`. `external` é True
                quando o host não é a própria máquina, e então `process()`
                exige `allow_external`.
            model: o preset de prompts. Entra em `output_version`.
            served: nome do modelo no pedido. Obrigatório num servidor fora
                da máquina, que serve vários e cobra por chamada. Num servidor
                local, sem ele, o leitor pergunta ao servidor qual é o único
                que ele serve, que é o caso do `llama-server`, na primeira
                vez que precisa da versão de saída.
            api_key: credencial, enviada como `Bearer`. Nenhum servidor local
                a pede.
            prices: dólares por milhão de tokens de entrada e de saída, para
                que `usage["usd"]` tenha valor. A biblioteca não traz tabela
                de preços: o número é de quem chama, e envelhece.
            layout: detector de regiões. Com ele, um chunk por região com a
                caixa dela; sem ele, a página inteira num chunk.
            concurrency: chamadas simultâneas por página, uma por região.
                Acima de 1 pede `llama-server -np <n>`.
            timeout: segundos por chamada.
            retries: quantas vezes repetir uma chamada que o servidor recusou
                por carga (HTTP 429 ou 5xx), que esgotou o `timeout` ou cuja
                conexão caiu, antes de a página falhar. `0`, o padrão, não
                repete. A espera dobra a cada tentativa a partir de um
                segundo, ou segue o `Retry-After` que o servidor mandar. Um
                servidor local ausente não é repetido: sobe como
                `ConnectionError` e interrompe o documento; num servidor fora
                da máquina, a conexão recusada é mais uma falha a repetir, e
                depois é falha da página.
            max_tokens: teto de tokens de saída por chamada. Uma folha densa
                cabe em 4096; o teto corta uma repetição em laço.
            reasoning: o esforço de pensamento, enviado como
                `reasoning_effort` (`"none"`, `"low"`, ...); `None` deixa o
                padrão do servidor. O pensamento gasta o teto de `max_tokens`,
                e um modelo que pensa muito pode esgotá-lo antes de transcrever
                a folha. Entra em `output_version`.
        """
        if model not in PRESETS:
            raise ValueError(f"model={model!r} desconhecido; aceitos: {sorted(PRESETS)}")
        self.url = url.rstrip("/")
        self.model: Model = model
        self.served = served
        self.api_key = api_key
        self.prices = prices
        self.layout = layout
        self.concurrency = concurrency
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.reasoning = reasoning
        if retries < 0:
            raise ValueError("retries não pode ser negativo")
        self.retries = retries
        self.external = urlparse(self.url).hostname not in _LOOPBACK
        if self.external and served is None:
            raise ValueError("served= é obrigatório num servidor fora da máquina")
        self.usage: dict[str, float] = {"calls": 0.0, "tokens_in": 0.0, "tokens_out": 0.0}
        # Com `concurrency` > 1 as regiões de uma página chamam o servidor de
        # várias threads, e cada soma em `usage` é ler, somar e gravar.
        self._counting = threading.Lock()
        if prices is not None:
            self.usage["usd"] = 0.0

    @property
    def output_version(self) -> str:
        """Modelo servido, preset e detector: o que muda a leitura sem mudar o nome."""
        if self.served is None:
            self.served = self._served_model()
        layout = self.layout.output_version if self.layout is not None else "page"
        version = f"3:{self.served}:{self.model}:{layout}"
        return version + (f":reasoning={self.reasoning}" if self.reasoning is not None else "")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _served_model(self) -> str:
        data = self._post(urllib.request.Request(f"{self.url}/v1/models", headers=self._headers()))
        try:
            served = cast("list[dict[str, str]]", data["data"])[0]["id"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"o servidor não listou um modelo: {str(data)[:300]}") from exc
        return served.rsplit("/", 1)[-1]

    def _ask(self, image: bytes, prompt: str) -> str:
        payload: dict[str, object] = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64," + base64.b64encode(image).decode()
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "temperature": 0,
            "max_tokens": self.max_tokens,
        }
        if self.served is not None:
            payload["model"] = self.served
        if self.reasoning is not None:
            payload["reasoning_effort"] = self.reasoning
        request = urllib.request.Request(
            f"{self.url}/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers=self._headers(),
        )
        data = self._post(request)
        self._count(data.get("usage"))
        try:
            choice = cast("list[dict[str, object]]", data["choices"])[0]
            content = cast("dict[str, object]", choice["message"])["content"]
            if not isinstance(content, str):
                raise TypeError(type(content).__name__)
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"resposta sem texto: {str(data)[:300]}") from exc
        # O teto de tokens cortou a resposta no meio: um texto pela metade, ou
        # um laço que não terminou. `process` fica com a leitura barata.
        if choice.get("finish_reason") == "length":
            raise RuntimeError(f"a resposta foi cortada no teto de {self.max_tokens} tokens")
        return content

    def _post(self, request: urllib.request.Request) -> dict[str, object]:
        """O corpo da resposta como dicionário; a falha passageira é repetida `retries` vezes.

        A espera segue o `Retry-After` do servidor, ou dobra a partir de um
        segundo. A última tentativa deixa a falha subir como veio.
        """
        for attempt in range(self.retries):
            try:
                return self._send(request)
            except _TransientError as exc:
                time.sleep(exc.wait if exc.wait is not None else float(2**attempt))
        return self._send(request)

    def _send(self, request: urllib.request.Request) -> dict[str, object]:
        """Uma chamada ao servidor: o corpo como dicionário, ou a falha classificada.

        `_TransientError` é a falha que outra tentativa pode resolver; o
        servidor local ausente é `ConnectionError`, que interrompe o documento.
        O `urllib` só embrulha em `URLError` o envio do pedido; o que acontece
        depois chega com o tipo cru.
        """
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                data: object = json.load(resp)
        except urllib.error.HTTPError as exc:
            # Subclasse de URLError, separada para que um erro do servidor não
            # se apresente como servidor ausente.
            body = exc.read().decode(errors="replace")[:300]
            retry_after = exc.headers.get("Retry-After")
            exc.close()
            message = f"o servidor respondeu {exc.code}: {body}"
            if exc.code == 429 or exc.code >= 500:
                raise _TransientError(message, _seconds(retry_after)) from exc
            raise RuntimeError(message) from exc
        except urllib.error.URLError as exc:
            message = f"sem servidor em {self.url}; ver docs/how-to/vlm.md"
            if self.external:
                raise _TransientError(message) from exc
            raise ConnectionError(message) from exc
        except OSError as exc:
            raise _TransientError(f"a resposta do servidor não pôde ser lida: {exc!r}") from exc
        except ValueError as exc:
            raise RuntimeError(f"a resposta do servidor não pôde ser lida: {exc!r}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"a resposta do servidor não é um objeto JSON: {str(data)[:300]}")
        return cast("dict[str, object]", data)

    def _count(self, usage: object) -> None:
        """Soma os tokens de uma resposta ao contador do leitor, sob a trava."""
        tokens_in = tokens_out = 0.0
        if isinstance(usage, dict):
            counts = cast("dict[str, object]", usage)
            tokens_in = float(cast("int", counts.get("prompt_tokens", 0) or 0))
            tokens_out = float(cast("int", counts.get("completion_tokens", 0) or 0))
            # Um modelo que pensa cobra o pensamento como saída, e há servidor
            # compatível que o deixa fora de `completion_tokens` e dentro de
            # `total_tokens`. O total menos a entrada é o que foi cobrado.
            total = float(cast("int", counts.get("total_tokens", 0) or 0))
            tokens_out = max(tokens_out, total - tokens_in)
        with self._counting:
            self.usage["calls"] += 1
            self.usage["tokens_in"] += tokens_in
            self.usage["tokens_out"] += tokens_out
            if self.prices is not None:
                self.usage["usd"] += (
                    tokens_in * self.prices[0] + tokens_out * self.prices[1]
                ) / 1e6

    def read(self, view: PageView) -> Sequence[Chunk]:
        """Um chunk por região com detector, ou um por página sem ele."""
        from PIL import Image

        # A imagem é renderizada no thread chamador, antes de qualquer
        # chamada em paralelo: o pdfium não é seguro entre threads.
        image = view.image(grayscale=False)
        page = view.page
        with Image.open(io.BytesIO(image)) as decoded:
            pixels = decoded.convert("RGB")
        # Numa folha de uma cor só não há o que ler, e o GLM-OCR responde a
        # ela com um comentário em inglês, que viraria o texto da página.
        if pixels.getcolors(1) is not None:
            return []
        prompts = PRESETS[self.model]
        # Num escaneamento degradado o detector devolve a folha como uma
        # imagem só, ou nada: a página inteira é a única região que resta.
        regions: Sequence[Region]
        if self.layout is None:
            regions = ()
        elif view.regions is not None and view.regions_version == self.layout.output_version:
            # `process(layout=)` com o mesmo detector já detectou nesta renderização.
            regions = view.regions
        else:
            regions = self.layout.detect(image)
        if not regions:
            text = _clean(self._ask(image, prompts["text"]))
            return [self._chunk(page, _FULL_PAGE, text, 0)] if text else []
        crops = _crops(pixels, regions)

        def ask(pair: tuple[Region, bytes]) -> str:
            region, crop = pair
            if region.label == "table":
                return _clean(_rows(self._ask(crop, prompts["table"])))
            return _clean(self._ask(crop, prompts["text"]))

        if self.concurrency > 1 and len(crops) > 1:
            with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
                texts = list(pool.map(ask, zip(regions, crops, strict=True)))
        else:
            texts = [ask(pair) for pair in zip(regions, crops, strict=True)]
        chunks: list[Chunk] = []
        for region, text in zip(regions, texts, strict=True):
            if text:
                chunks.append(self._chunk(page, region.bbox, text, len(chunks), region.label))
        return chunks

    def _chunk(
        self, page: Page, bbox: BBox, text: str, order: int, kind: str | None = None
    ) -> Chunk:
        return Chunk.make(page, bbox, self.name, text, reading_order=order, kind=kind)


class _TransientError(RuntimeError):
    """Uma falha que outra tentativa pode resolver; `wait` é a espera que o servidor pediu.

    É um `RuntimeError`: esgotadas as tentativas, `process` a trata como a falha da página.
    """

    def __init__(self, message: str, wait: float | None = None) -> None:
        super().__init__(message)
        self.wait = wait


def _seconds(retry_after: str | None) -> float | None:
    """Os segundos de um `Retry-After` numérico; a forma em data, rara, fica com a espera padrão."""
    if retry_after is None:
        return None
    try:
        return max(0.0, float(retry_after))
    except ValueError:
        return None


def _crops(img: Image.Image, regions: Sequence[Region]) -> list[bytes]:
    """Um PNG por região, recortado da página; Pillow puro, fora do lock do pdfium."""
    out: list[bytes] = []
    for region in regions:
        x0, y0, x1, y1 = region.bbox.to_pixels(*img.size)
        crop = img.crop((x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)))
        buffer = io.BytesIO()
        crop.save(buffer, format="PNG")
        out.append(buffer.getvalue())
    return out
