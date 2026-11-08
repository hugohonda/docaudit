# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# pyright: reportMissingImports=false, reportUnknownVariableType=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportAttributeAccessIssue=false
#
# numpy e onnxruntime vêm pelo extra `layout`, e o pyright roda sobre a instalação
# do núcleo, sem eles. O que sai daqui é um modelo Pydantic com floats.
"""Detecção de layout com o PP-DocLayoutV3, em ONNX Runtime.

É o detector que o PaddleOCR-VL usa antes do modelo de visão e linguagem: os
modelos de leitura foram treinados sobre recortes de região, e mandar a página
inteira produz texto alucinado. Aqui ele serve para recortar a página em
regiões com rótulo, caixa e ordem de leitura, e para descartar por estrutura o
que não é conteúdo: cabeçalho, rodapé, número de folha, carimbo, a tarja de
assinatura na margem.

O grafo recebe a página em 800 por 800 e devolve trezentas consultas, cada
uma com uma pontuação por classe, uma caixa e um voto de precedência sobre
as outras. Uma consulta entra uma vez, com a sua melhor classe, quando a
pontuação passa do limiar. Não calibrado: é o valor de referência do
exportador.

O grafo devolve também a caixa que contém outras; `_overlaps` deixa uma de
cada par.

Os pesos baixam na primeira detecção, para `<DOCAUDIT_CACHE_DIR>/models`, e
são conferidos pelo SHA-256.
"""

from __future__ import annotations

import hashlib
import io
import tempfile
import threading
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from docaudit.cache import default_cache_path
from docaudit.types import BBox, Region

__all__ = ["DROP_DEFAULT", "LABELS", "PPDocLayout", "Region", "regions_from"]

WEIGHTS_URL = "https://huggingface.co/phungpx/PP-DocLayoutV3-ONNX/resolve/main/pp_doclayoutv3.onnx"
WEIGHTS_SHA256 = "29193c815d2d9a9db42cdebe400862fbdbf64e7e14c06f8b1f5064657c769b88"
INPUT_SIZE = 800

LABELS: tuple[str, ...] = (
    "abstract",
    "algorithm",
    "aside_text",
    "chart",
    "content",
    "formula",
    "doc_title",
    "figure_title",
    "footer",
    "footer",
    "footnote",
    "formula_number",
    "header",
    "header",
    "image",
    "inline_formula",
    "number",
    "paragraph_title",
    "reference",
    "reference_content",
    "seal",
    "table",
    "text",
    "text",
    "vision_footnote",
)
"""As 25 classes do exportador, na ordem das saídas do grafo."""

DROP_DEFAULT: tuple[str, ...] = (
    "aside_text",
    "footer",
    "footnote",
    "header",
    "image",
    "number",
    "seal",
)
"""Rótulos que não são conteúdo numa folha de autos: cabeçalho e rodapé, carimbo, figura."""


_LOADING = threading.Lock()
"""Serializa a carga do detector."""


def _unit(v: float) -> float:
    return min(max(v, 0.0), 1.0)


def _sigmoid(x: Any) -> Any:
    import numpy as np

    return 1.0 / (1.0 + np.exp(-np.clip(x, -500.0, 500.0)))


def regions_from(
    logits: Any, boxes: Any, order_logits: Any, *, threshold: float, drop: Sequence[str]
) -> list[Region]:
    """Converte as saídas do grafo, já sem a dimensão de lote, em regiões ordenadas.

    Cada consulta entra uma vez, com a classe de maior pontuação; a ordem de
    leitura vem dos votos de precedência entre consultas. As caixas chegam em
    centro e dimensões, normalizadas, e saem em cantos, presas a [0, 1].
    """
    import numpy as np

    scores = _sigmoid(np.asarray(logits, dtype=np.float64))
    best = scores.argmax(axis=1)
    kept = [int(q) for q in range(scores.shape[0]) if scores[q, best[q]] >= threshold]
    if not kept:
        return []
    precedence = _sigmoid(np.asarray(order_logits, dtype=np.float64))
    votes = np.triu(precedence, 1).sum(axis=0) + np.tril(1.0 - precedence.T, -1).sum(axis=0)
    rank = np.empty(len(votes), dtype=int)
    rank[np.argsort(votes, kind="stable")] = np.arange(len(votes))

    out: list[Region] = []
    for q in sorted(kept, key=lambda q: int(rank[q])):
        label = LABELS[int(best[q])]
        if label in drop:
            continue
        cx, cy, w, h = (float(v) for v in boxes[q])
        x0, y0, x1, y1 = (_unit(v) for v in (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
        if x1 <= x0 or y1 <= y0:
            continue
        out.append(Region(label=label, bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1)))
    # Depois do `drop`: um cabeçalho descartado não leva junto o título que
    # cobre, que o leitor ainda lê.
    return _overlaps(out)


_VISUAL = frozenset({"image", "table", "seal", "chart"})


def _inside(a: BBox, b: BBox) -> float:
    """A fração da caixa menor que a interseção cobre."""
    smaller = min(a.area, b.area)
    return a.intersection(b) / smaller if smaller else 0.0


def _overlaps(regions: list[Region]) -> list[Region]:
    """Uma região por trecho da página, pela regra de `filter_overlap_boxes` do PaddleX.

    - a fórmula na linha com mais da metade dentro de outra região sai;
    - de duas regiões em que a interseção passa de 0,7 da menor, sai a
      menor; menos quando uma é figura, carimbo ou gráfico e a outra não é
      texto, porque as duas são lidas de jeitos diferentes.

    Duas partes da regra do PaddleX ficam de fora. A caixa com menos de 6
    pixels de lado, porque aqui a caixa é normalizada. E o descarte de toda
    `reference`: num diário o detector põe esse rótulo em blocos comuns, e
    tirá-los perdia valores que só eles tinham.
    Com a regra geral, a lista fica e os itens dentro dela saem.
    """
    dropped: set[int] = set()
    for i, a in enumerate(regions):
        for j in range(i + 1, len(regions)):
            if i in dropped:
                break
            if j in dropped:
                continue
            b = regions[j]
            ratio = _inside(a.bbox, b.bbox)
            if "inline_formula" in (a.label, b.label) and ratio > 0.5:
                dropped |= {k for k, r in ((i, a), (j, b)) if r.label == "inline_formula"}
                continue
            if ratio <= 0.7:
                continue
            # Figura, carimbo ou gráfico junto de outra coisa ficam os dois, menos
            # a tabela sobre texto: a figura é lida como imagem, o texto não.
            labels = {a.label, b.label}
            mixed = len(labels) > 1 and bool(labels & _VISUAL)
            if mixed and ("table" not in labels or labels <= _VISUAL):
                continue
            dropped.add(j if a.bbox.area >= b.bbox.area else i)
    return [r for k, r in enumerate(regions) if k not in dropped]


class PPDocLayout:
    """Detecta regiões de uma página renderizada."""

    def __init__(
        self,
        threshold: float = 0.5,
        drop: Sequence[str] = DROP_DEFAULT,
        *,
        threads: int | None = None,
    ) -> None:
        """Fixa o limiar de pontuação e os rótulos descartados; nada é carregado aqui.

        Args:
            threshold: pontuação mínima de uma consulta. Não calibrado: é o
                valor de referência do exportador.
            drop: rótulos que não viram região. Entram em `output_version`,
                porque mudam o que um leitor por região devolve.
            threads: threads do ONNX Runtime dentro de uma inferência, como
                em `PPOCR`. `None` usa todos os núcleos.
        """
        self.threads = threads
        self.threshold = threshold
        self.drop = tuple(drop)
        self.output_version = (
            f"pp_doclayoutv3:2:{WEIGHTS_SHA256[:8]}:{threshold}:{'+'.join(sorted(self.drop))}"
        )
        self._session: Any = None

    @staticmethod
    def weights_path() -> Path:
        """Onde os pesos ficam: `<cache>/models/pp_doclayoutv3.onnx`."""
        return default_cache_path().parent / "models" / "pp_doclayoutv3.onnx"

    def _load(self) -> Any:
        # `run` do ONNX Runtime aceita chamadas simultâneas; a carga não: duas
        # threads baixariam e abririam os pesos ao mesmo tempo.
        with _LOADING:
            return self._load_once()

    def _load_once(self) -> Any:
        if self._session is None:
            try:
                import onnxruntime as ort
            except ModuleNotFoundError as exc:  # pragma: no cover - depende do ambiente
                raise ModuleNotFoundError(
                    "o detector de layout precisa do extra: uv add 'docaudit[layout]'"
                ) from exc
            path = self.weights_path()
            if not path.exists():
                _download(WEIGHTS_URL, path, WEIGHTS_SHA256)
            options = ort.SessionOptions()
            options.log_severity_level = 3
            if self.threads is not None:
                options.intra_op_num_threads = self.threads
            self._session = ort.InferenceSession(
                str(path), sess_options=options, providers=["CPUExecutionProvider"]
            )
        return self._session

    def detect(self, image: bytes) -> Sequence[Region]:
        """Regiões de uma página em PNG, na ordem de leitura, sem as de `drop`."""
        try:
            import numpy as np
        except ModuleNotFoundError as exc:  # pragma: no cover - depende do ambiente
            raise ModuleNotFoundError(
                "o detector de layout precisa do extra: uv add 'docaudit[layout]'"
            ) from exc
        from PIL import Image

        with Image.open(io.BytesIO(image)) as img:
            square = img.convert("RGB").resize((INPUT_SIZE, INPUT_SIZE), Image.Resampling.BICUBIC)
        pixels = np.asarray(square, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
        # Só as três saídas que entram no resultado: a cabeça de máscaras é a
        # mais cara do grafo e não é pedida.
        logits, boxes, order = self._load().run(
            ["logits", "pred_boxes", "order_logits"], {"pixel_values": pixels}
        )
        return regions_from(logits[0], boxes[0], order[0], threshold=self.threshold, drop=self.drop)


def _download(url: str, dest: Path, sha256: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Um arquivo temporário por chamada, na mesma pasta: processos que baixam
    # ao mesmo tempo na primeira execução não escrevem no mesmo `.part`, e o
    # `replace` final é atômico.
    digest = hashlib.sha256()
    with (
        urllib.request.urlopen(url, timeout=120) as resp,
        tempfile.NamedTemporaryFile(dir=dest.parent, suffix=".part", delete=False) as out,
    ):
        partial = Path(out.name)
        while block := resp.read(1 << 20):
            digest.update(block)
            out.write(block)
    if digest.hexdigest() != sha256:
        partial.unlink()
        raise RuntimeError(f"pesos em {url} não batem com o SHA-256 esperado")
    partial.replace(dest)
