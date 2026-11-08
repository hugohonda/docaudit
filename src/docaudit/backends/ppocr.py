# pyright: reportMissingImports=false, reportUnknownVariableType=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportAttributeAccessIssue=false
#
# rapidocr e numpy vêm pelo extra `ppocr`, e o pyright roda sobre a instalação
# do núcleo, sem eles. Tudo o que entra daqui no resto do pacote passa por
# float() ou por um modelo Pydantic, e nenhuma API pública expõe Any.
"""Backend sobre os pesos PP-OCR do PaddleOCR, em ONNX Runtime.

Os pesos são os do PaddleOCR exportados para ONNX pelo RapidOCR. Assim o
backend não depende do paddlepaddle, que em CPU é mais de uma ordem de
grandeza mais lento com os mesmos pesos.

Dois conjuntos de pesos:

- `v5-latin`, o barato: detecção `PP-OCRv5_mobile_det` e reconhecimento
  `latin_PP-OCRv5_mobile_rec`, o reconhecedor latino do PaddleOCR. O
  dicionário cobre os acentos, o cedilha, `º`, `ª` e `§`.
- `v6-medium`, o caro: detecção e reconhecimento `PP-OCRv6_medium`, num
  reconhecedor único de cinquenta línguas, a quatro vezes o custo.

Não é um modelo de visão e linguagem: não segue prompt nem descreve layout.

A dependência entra pelo extra `ppocr`, e o import é tardio. Os pesos baixam
na primeira leitura, para `<DOCAUDIT_CACHE_DIR>/models`.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, get_args

from docaudit.cache import default_cache_path
from docaudit.types import BBox, Chunk

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence

    from PIL import Image

    from docaudit.pdf import PageView
    from docaudit.types import Page, Turn

__all__ = ["PPOCR"]

_ENGINE = threading.Lock()
"""Serializa a carga e a inferência do RapidOCR.

O ONNX Runtime derruba o processo quando duas threads rodam o RapidOCR ao mesmo
tempo, mesmo em motores separados. Com o lock, `workers` > 1 ainda paraleliza a
renderização e a camada de texto; o OCR roda um por vez, e o ONNX Runtime usa os
núcleos dentro de cada chamada.
"""


def _rapidocr_version() -> str:
    """A versão do RapidOCR, que escolhe o arquivo de pesos e o pré-processamento."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("rapidocr")
    except PackageNotFoundError:
        return "ausente"


def _sha256(path: Path) -> str:
    """O começo do SHA-256 do arquivo: a identidade de um peso que não tem nome."""
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()[:12]


Models = Literal["v5-latin", "v6-medium"]
Engine = Literal["auto", "onnxruntime", "cuda", "openvino"]

_WEIGHTS: dict[Models, tuple[str, str]] = {
    "v5-latin": ("PP-OCRv5_mobile_det", "latin_PP-OCRv5_mobile_rec"),
    "v6-medium": ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"),
}


def _shrink_after_each_run(session: Any) -> None:
    """Faz a sessão devolver à GPU, depois de cada inferência, a reserva que ficou sem uso.

    O ONNX Runtime guarda na reserva todo bloco que já alocou. Página após
    página, a reserva se fragmenta, e uma página que pede um bloco grande
    falha com a placa meio vazia. Devolver a sobra a cada inferência mantém
    a memória na altura da página corrente. O RapidOCR chama `run` sem
    opções; a sessão passa a chamá-lo com elas.
    """
    import onnxruntime

    options = onnxruntime.RunOptions()
    options.add_run_config_entry("memory.enable_memory_arena_shrinkage", "gpu:0")
    run = session.run

    def shrinking(output_names: Any, input_feed: Any) -> Any:
        return run(output_names, input_feed, options)

    session.run = shrinking


@contextlib.contextmanager
def _without_shape_cache() -> Generator[None]:
    """Monta as sessões do OpenVINO sem o cache de formatos da CPU.

    O OpenVINO guarda um núcleo compilado para cada formato de entrada. O
    RapidOCR monta cada lote de reconhecimento na largura da linha mais larga,
    então quase todo lote é um formato novo: o cache quase não acerta e cresce
    até a memória do processo acabar. O RapidOCR só repassa ao motor as
    propriedades que conhece; esta é somada a elas enquanto as sessões nascem.
    """
    from rapidocr.inference_engine.openvino.device_config import CPUConfig

    build = CPUConfig.get_config

    def without_cache(self: Any) -> dict[str, Any]:
        return {**build(self), "CPU_RUNTIME_CACHE_CAPACITY": "0"}

    CPUConfig.get_config = without_cache
    try:
        yield
    finally:
        CPUConfig.get_config = build


def _require_cuda(providers: Sequence[str]) -> None:
    """Falha se a sessão não ficou com o provedor CUDA.

    O ONNX Runtime que não acha o CUDA ou o cuDNN não falha: cria a sessão na
    CPU e segue. Pedir a GPU e ler na CPU calado gravaria no cache, sob a
    versão da GPU, uma leitura que não é dela.
    """
    if "CUDAExecutionProvider" not in providers:
        raise RuntimeError(
            "PP-OCR: engine='cuda' sem o provedor CUDA do ONNX Runtime "
            f"(sessão com {list(providers)}); instale onnxruntime-gpu no lugar de onnxruntime"
        )


def _broken_install(exc: BaseException) -> ImportError | None:
    """O erro de instalação na cadeia de causas de `exc`, como um erro de import com o remédio.

    O RapidOCR embrulha qualquer exceção do OpenCV num erro próprio, e um
    `cv2` sem `resize` chega igual a uma imagem que não se redimensiona. Um
    módulo que falta, ou que perdeu um nome, não é desta página: falharia em
    todas, e a cascata as passaria adiante caladas.
    """
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, ImportError | AttributeError):
            message = f"PP-OCR: a instalação está quebrada ({type(seen).__name__}: {seen})"
            if "cv2" in str(seen):
                message += (
                    ". opencv-python, opencv-python-headless e opencv-contrib-python "
                    "instalam o mesmo módulo cv2, e remover um apaga o dos outros: "
                    "reinstale o que fica com --force-reinstall"
                )
            return ImportError(message)
        seen = seen.__cause__ or seen.__context__
    return None


def _turned(poly: Sequence[Sequence[float]], crop: Any) -> bool:
    """Se o RapidOCR girou este recorte um quarto de volta antes de reconhecê-lo.

    Ele gira o recorte alto para deitá-lo, em `get_rotate_crop_image`. Um
    recorte que sai com a orientação oposta à da caixa detectada foi girado:
    a decisão se lê do próprio recorte, sem repetir a regra dele.
    """
    import math

    def dist(a: Sequence[float], b: Sequence[float]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    box_tall = max(dist(poly[0], poly[3]), dist(poly[1], poly[2])) > max(
        dist(poly[0], poly[1]), dist(poly[2], poly[3])
    )
    crop_tall = crop.shape[0] > crop.shape[1]
    return box_tall != crop_tall


def _wide(lines: Sequence[tuple[BBox, str, float]], threshold: float) -> int:
    """Quantas linhas entregues são mais largas que altas: as escritas deitadas e inteiras."""
    return sum(
        1
        for box, text, score in lines
        if text.strip() and score >= threshold and box.x1 - box.x0 > box.y1 - box.y0
    )


class PPOCR:
    """Lê uma página com o PP-OCR e devolve um chunk por linha detectada.

    O nome traz os pesos (`ppocr-v5-latin`, `ppocr-v6-medium`): com o PP-OCR
    nos dois níveis, cada linha diz qual deles a leu. Um reconhecedor próprio,
    como o de um ajuste fino, acrescenta ao nome o começo do hash do arquivo
    (`ppocr-v5-latin+3fa9c1d2e4b0`): dois ajustes do mesmo modelo saem distintos
    em `Chunk.source`. O backend se registra como `ppocr`.
    """

    external = False

    def __init__(
        self,
        models: Models = "v5-latin",
        *,
        rec: Path | str | None = None,
        keys: Path | str | None = None,
        det: Path | str | None = None,
        threads: int | None = None,
        engine: Engine = "auto",
    ) -> None:
        """Escolhe os pesos. Nada é carregado até a primeira leitura.

        Args:
            models: os pesos do detector e do reconhecedor.
            rec: um reconhecedor ONNX no lugar do de `models`, que segue
                escolhendo o detector. Vem com `keys`.
            keys: o dicionário de caracteres de `rec`, um por linha, na
                ordem do treino. O RapidOCR prefere a lista gravada no
                próprio ONNX quando ela existe; o export do PaddleOCR não a
                grava, e então vale este arquivo.
            det: um detector ONNX no lugar do de `models`. Com ele, nada do
                detector é baixado: é o arquivo que uma imagem de contêiner
                guarda para não depender da rede na primeira leitura.
            threads: threads do motor dentro de uma inferência. `None`
                usa todos os núcleos, o certo para um processo só. Com vários
                processos lendo ao mesmo tempo, cada um disputa todos os
                núcleos; ver a receita de lote em `docs/recipes.md`. Não entra
                em `output_version`: muda o tempo, não a leitura.
            engine: o motor da detecção e do reconhecimento. `"auto"`, o
                padrão, é o OpenVINO na CPU quando o extra `openvino` está
                instalado, e o ONNX Runtime quando não está. `"onnxruntime"` e `"openvino"`
                fixam um dos dois. `"cuda"` é o ONNX Runtime na GPU: pede o
                `onnxruntime-gpu` no lugar do `onnxruntime` e falha na primeira
                leitura se a sessão não ficar na GPU. Fora o ONNX Runtime na CPU,
                o motor entra em `output_version`: outro motor parte e arredonda
                algumas linhas de outro jeito, e a leitura de um não serve pela
                do outro.

        Raises:
            ValueError: `models` ou `engine` desconhecido, ou só um de `rec` e
                `keys`.
            FileNotFoundError: `rec`, `keys` ou `det` não existe.
        """
        if models not in _WEIGHTS:
            raise ValueError(f"models={models!r} desconhecido; aceitos: {sorted(_WEIGHTS)}")
        if engine not in get_args(Engine):
            raise ValueError(f"engine={engine!r} desconhecido; aceitos: {list(get_args(Engine))}")
        if (rec is None) != (keys is None):
            raise ValueError("rec e keys vêm juntos: o reconhecedor e o dicionário dele")
        self.models: Models = models
        self.threads = threads
        if engine == "auto":
            engine = "openvino" if importlib.util.find_spec("openvino") else "onnxruntime"
        self.engine: Engine = engine
        self.own = (Path(rec), Path(keys)) if rec is not None and keys is not None else None
        self.own_det = Path(det) if det is not None else None
        self.name = f"ppocr-{models}"
        # Os nomes dos pesos entram na versão de saída, e com ela na chave do
        # cache: trocar de modelo não pode servir a leitura do anterior. Um
        # peso próprio entra pelo hash do arquivo, que muda a cada treino sem
        # mudar o caminho; o do reconhecedor leva também o do dicionário.
        det_name, rec_name = _WEIGHTS[models]
        if self.own_det is not None:
            det_name = f"det={_sha256(self.own_det)}"
            self.name += f"+{det_name}"
        if self.own is not None:
            rec_hash, keys_hash = (_sha256(p) for p in self.own)
            self.name += f"+{rec_hash}"
            rec_name = f"rec={rec_hash}:keys={keys_hash}"
        weights = f"{det_name}+{rec_name}"
        self.output_version = f"3:{weights}:rapidocr={_rapidocr_version()}"
        if engine != "onnxruntime":
            self.output_version += f":{engine}"
        self._engine: Any = None
        # A sessão que caiu na CPU não volta para a GPU: a falha fica guardada, e
        # a página seguinte falha sem montar o motor de novo.
        self._failure: RuntimeError | None = None

    def _load(self) -> Any:
        """O motor, construído na primeira chamada; quem chama segura `_ENGINE`."""
        if self._failure is not None:
            raise RuntimeError(*self._failure.args)
        if self._engine is None:
            try:
                from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
            except ModuleNotFoundError as exc:  # pragma: no cover - depende do ambiente
                raise ModuleNotFoundError(
                    "o backend 'ppocr' precisa do extra: uv add 'docaudit[ppocr]'"
                ) from exc
            weights: dict[str, object]
            if self.models == "v5-latin":
                weights = {
                    "Det.ocr_version": OCRVersion.PPOCRV5,
                    "Det.model_type": ModelType.MOBILE,
                    "Rec.ocr_version": OCRVersion.PPOCRV5,
                    "Rec.lang_type": LangRec.LATIN,
                    "Rec.model_type": ModelType.MOBILE,
                }
            else:
                weights = {
                    "Det.ocr_version": OCRVersion.PPOCRV6,
                    "Det.model_type": ModelType.MEDIUM,
                    "Rec.ocr_version": OCRVersion.PPOCRV6,
                    "Rec.model_type": ModelType.MEDIUM,
                }
            if self.own is not None:
                weights["Rec.model_path"], weights["Rec.rec_keys_path"] = map(str, self.own)
            if self.own_det is not None:
                weights["Det.model_path"] = str(self.own_det)
            # O classificador de orientação de linha fica desligado: ele julga
            # toda linha, e vira linhas horizontais que estavam certas. A linha
            # vertical é tratada em `_read`.
            params: dict[str, object] = {
                "Global.use_cls": False,
                "Global.log_level": "warning",
                "Global.model_root_dir": str(default_cache_path().parent / "models"),
                **weights,
            }
            threads = "EngineConfig.onnxruntime.intra_op_num_threads"
            if self.engine == "openvino":
                # O OpenVINO lê os mesmos arquivos ONNX: só a execução muda.
                try:
                    import openvino  # noqa: F401  # pyright: ignore[reportUnusedImport] - o RapidOCR só o importa ao montar a etapa
                except ModuleNotFoundError as exc:  # pragma: no cover - depende do ambiente
                    raise ModuleNotFoundError(
                        "engine='openvino' precisa do extra: uv add 'docaudit[openvino]'"
                    ) from exc
                from rapidocr.utils.typings import EngineType

                params["Det.engine_type"] = params["Rec.engine_type"] = EngineType.OPENVINO
                threads = "EngineConfig.openvino.inference_num_threads"
            if self.threads is not None:
                params[threads] = self.threads
            if self.engine == "cuda":
                import onnxruntime

                # O onnxruntime-gpu do pip traz o CUDA e o cuDNN em pacotes à
                # parte, que só valem carregados antes da sessão.
                onnxruntime.preload_dlls()
                # A heurística do cuDNN escolhe o algoritmo uma vez, e não a cada
                # largura de linha nova. A reserva cresce só o que a operação
                # pede: dobrando, alguns processos na mesma placa a esgotam numa
                # página grande.
                cuda = "EngineConfig.onnxruntime.cuda_ep_cfg"
                params["EngineConfig.onnxruntime.use_cuda"] = True
                params[f"{cuda}.cudnn_conv_algo_search"] = "HEURISTIC"
                params[f"{cuda}.arena_extend_strategy"] = "kSameAsRequested"
            engine = RapidOCR(params=params)
            # As etapas nascem aqui, e não dentro da primeira leitura: lá, o peso
            # que falta ou a rede fora viram uma falha por página, em toda página.
            # Aqui, a exceção de download para o documento.
            with _without_shape_cache() if self.engine == "openvino" else contextlib.nullcontext():
                det = engine._load_det_model()  # pyright: ignore[reportPrivateUsage]
                rec = engine._load_rec_model()  # pyright: ignore[reportPrivateUsage]
            if self.engine == "cuda":
                # O RapidOCR não expõe a sessão de outro jeito.
                try:
                    for stage in (det, rec):
                        _require_cuda(stage.session.session.get_providers())
                except RuntimeError as exc:
                    self._failure = exc
                    raise
                for stage in (det, rec):
                    _shrink_after_each_run(stage.session.session)
            self._engine = engine
        return self._engine

    def prepare(self) -> None:
        """Baixa o que faltar dos pesos e abre as sessões agora, e não na primeira leitura.

        Quem chama no início do processo, ou na construção da imagem, fica sem
        depender da rede ao ler: com o arquivo no lugar e o hash certo, o RapidOCR
        não baixa nada. Inclui o detector de `models=`, que `rec=` não
        substitui e `det=` sim.
        """
        with _ENGINE:
            self._load()

    def read(self, view: PageView) -> Sequence[Chunk]:
        """Transcreve a página inteira, uma linha por chunk, de cima para baixo."""
        # Em RGB, o formato para o qual os pesos foram feitos. A matriz vai direto ao
        # motor: o PNG não muda pixel e custava um quarto da página.
        return self._read(view.page, view.pixels(grayscale=False))

    def _read(self, page: Page, image: Image.Image) -> Sequence[Chunk]:
        """Detecta, recorta e reconhece com as etapas do RapidOCR, num lote só.

        Uma página digitalizada de lado tem a maioria das linhas altas: lida assim, cada
        coluna de uma tabela sai separada da sua linha. Ela é lida de novo girada um
        quarto de volta, e fica a leitura com mais linhas deitadas (`_wide`); no empate,
        a página em pé. O detector parte uma linha escrita de pé em pedaços de uma palavra
        ou menos, altos ou quase quadrados: a orientação certa é a que tem mais linhas
        inteiras. A tarja de margem, vertical, faz a maioria alta numa página de poucas
        linhas; girada, ela sai inteira, mas o corpo sai em pedaços, e a página fica em
        pé. Cada caixa volta ao sistema da imagem com o giro em `turn`.
        """
        try:
            import numpy as np
        except ModuleNotFoundError as exc:  # pragma: no cover - depende do ambiente
            raise ModuleNotFoundError(
                "o backend 'ppocr' precisa do extra: uv add 'docaudit[ppocr]'"
            ) from exc
        pixels = np.asarray(image.convert("RGB"))
        if pixels.ndim != 3 or min(pixels.shape[:2]) == 0:
            return []
        with _ENGINE:
            engine = self._load()
            lines, tall, flipped = self._recognize(engine, pixels)
            threshold = float(engine.cfg.Global.text_score)
            turn: Turn = 0
            if 2 * tall > len(lines):
                # O RapidOCR deita o recorte alto no sentido anti-horário; se a meia-volta
                # leu melhor, o texto sobe da base para o topo e a página gira no horário.
                candidate: Literal[90, 270] = 270 if 2 * flipped > tall else 90
                rotated = np.ascontiguousarray(np.rot90(pixels, 1 if candidate == 90 else -1))
                other, _, _ = self._recognize(engine, rotated)
                if _wide(other, threshold) > _wide(lines, threshold):
                    lines, turn = other, candidate

        chunks: list[Chunk] = []
        for box, text, score in lines:
            if not text.strip() or score < threshold:
                continue
            chunks.append(
                Chunk.make(
                    page,
                    box.unturned(turn),
                    self.name,
                    text,
                    confidence=min(max(float(score), 0.0), 1.0),
                    reading_order=len(chunks),
                    turn=turn,
                )
            )
        return chunks

    def _recognize(
        self, engine: Any, pixels: Any
    ) -> tuple[list[tuple[BBox, str, float]], int, int]:
        """As linhas desta matriz; e quantas eram altas e quantas leram melhor viradas.

        O RapidOCR gira um recorte alto um quarto de volta no sentido
        anti-horário, o que endireita texto escrito de cima para baixo. A tarja
        de margem de um tribunal é escrita de baixo para cima e chega de cabeça
        para baixo. Cada recorte girado é reconhecido também em meia-volta, no
        mesmo lote, e fica a leitura de maior confiança, como o EasyOCR faz com
        `rotation_info`. O corte de confiança do RapidOCR vem depois disso.
        """
        import numpy as np
        from rapidocr.main import RapidOCRError
        from rapidocr.utils.process_img import map_boxes_to_original

        height, width = pixels.shape[:2]
        try:
            resized, op_record = engine.preprocess_img(pixels)
            try:
                crops, detected = engine.detect_and_crop(resized, op_record)
            except RapidOCRError as exc:
                if _broken_install(exc) is not None:
                    raise
                return [], 0, 0
            # Um recorte sem largura ou altura vai ao ONNX Runtime como
            # tensor vazio; ele fica de fora antes de chegar ao motor.
            keep = [i for i, crop in enumerate(crops) if min(crop.shape[:2]) > 0]
            if not keep:
                return [], 0, 0
            crops = [crops[i] for i in keep]
            detected.boxes = detected.boxes[keep]
            turned = [i for i, crop in enumerate(crops) if _turned(detected.boxes[i], crop)]
            flipped = [np.ascontiguousarray(np.rot90(crops[i], 2)) for i in turned]
            recognized = engine.recognize_txt([*crops, *flipped])
        except Exception as exc:
            if (broken := _broken_install(exc)) is not None:
                raise broken from exc
            # Erros nativos do ONNX Runtime e do OpenCV chegam como tipos
            # próprios; a cascata trata a falha de leitura desta página como
            # `RuntimeError`.
            raise RuntimeError(f"PP-OCR: {type(exc).__name__}: {exc}") from exc
        texts = [str(t) for t in recognized.txts]
        scores = [float(v) for v in recognized.scores]
        won = 0
        for k, i in enumerate(turned):
            if scores[len(crops) + k] > scores[i]:
                texts[i], scores[i] = texts[len(crops) + k], scores[len(crops) + k]
                won += 1
        boxes = map_boxes_to_original(detected.boxes, op_record, height, width)
        lines = []
        for poly, text, score in zip(boxes, texts, scores, strict=False):
            xs, ys = [float(p[0]) for p in poly], [float(p[1]) for p in poly]
            bbox = BBox.from_pixels(
                min(xs), min(ys), max(xs), max(ys), width_px=width, height_px=height
            )
            lines.append((bbox, text, score))
        return lines, len(turned), won
