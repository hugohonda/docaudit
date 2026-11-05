"""O nome e a versão de saída do PP-OCR com um reconhecedor próprio, sem carregar o motor."""

import pytest
from tests.support import make_pdf
from tests.support.fixtures import TEXT_CENTRAL

from docaudit import process
from docaudit.backends.ppocr import (
    PPOCR,
    _require_cuda,
    _shrink_after_each_run,
    _without_shape_cache,
)


def _own(folder, weights: bytes, chars: str) -> PPOCR:
    """Um PPOCR sobre um reconhecedor e um dicionário gravados em `folder`."""
    folder.mkdir(exist_ok=True)
    rec, keys = folder / "rec.onnx", folder / "keys.txt"
    rec.write_bytes(weights)
    keys.write_text(chars)
    return PPOCR(rec=rec, keys=keys)


def test_an_own_recognizer_names_its_hash_and_keeps_the_detector(tmp_path):
    own = _own(tmp_path, b"pesos", "a\nb\n")

    assert own.name.startswith("ppocr-v5-latin+")
    assert "PP-OCRv5_mobile_det" in own.output_version
    assert "latin_PP-OCRv5_mobile_rec" not in own.output_version


def test_new_weights_or_a_new_dictionary_change_the_version(tmp_path):
    first = _own(tmp_path / "a", b"pesos", "a\n")
    weights = _own(tmp_path / "b", b"outros", "a\n")
    chars = _own(tmp_path / "c", b"pesos", "b\n")

    assert weights.name != first.name
    assert weights.output_version != first.output_version
    assert chars.name == first.name, "o nome segue os pesos; o dicionário entra na versão"
    assert chars.output_version != first.output_version


def test_the_recognizer_comes_with_its_dictionary(tmp_path):
    with pytest.raises(ValueError, match="juntos"):
        PPOCR(rec=tmp_path / "rec.onnx")


@pytest.mark.parametrize("engine", ["cuda", "openvino"])
def test_another_engine_reads_under_its_own_version(engine):
    default, other = PPOCR(engine="onnxruntime"), PPOCR(engine=engine)
    assert other.output_version == f"{default.output_version}:{engine}"
    assert other.name == default.name, "o leitor é o mesmo; muda o motor que o executa"


def test_auto_takes_openvino_only_when_it_is_installed(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda _: None)
    assert PPOCR().engine == "onnxruntime", "sem o extra, o motor de sempre"
    monkeypatch.setattr("importlib.util.find_spec", lambda _: object())
    assert PPOCR().engine == "openvino"
    assert PPOCR().output_version.endswith(":openvino"), "o motor resolvido entra na versão"


def test_an_unknown_engine_is_refused():
    with pytest.raises(ValueError, match="engine"):
        PPOCR(engine="tensorrt")  # pyright: ignore[reportArgumentType] - o valor errado é o teste


def test_a_gpu_session_runs_with_the_arena_shrinking_after_each_run():
    """A sessão chamada sem opções passa a rodar com a devolução da reserva."""
    pytest.importorskip("onnxruntime")
    seen = []

    class Session:
        def run(self, names, feed, run_options=None):
            seen.append(run_options)
            return "ok"

    session = Session()
    _shrink_after_each_run(session)
    assert session.run(["out"], {"x": 1}) == "ok"
    (options,) = seen
    assert options.get_run_config_entry("memory.enable_memory_arena_shrinkage") == "gpu:0"


def test_openvino_sessions_are_built_without_the_shape_cache():
    """A propriedade entra nas que o RapidOCR já repassa, e só enquanto as sessões nascem."""
    device = pytest.importorskip("rapidocr.inference_engine.openvino.device_config")
    config = device.CPUConfig({"inference_num_threads": 1})
    with _without_shape_cache():
        assert config.get_config() == {
            "INFERENCE_NUM_THREADS": "1",
            "CPU_RUNTIME_CACHE_CAPACITY": "0",
        }
    assert "CPU_RUNTIME_CACHE_CAPACITY" not in config.get_config()


def test_a_missing_weight_stops_at_load_and_not_page_by_page(monkeypatch):
    """A falha de download não é da página: sobe de `prepare`, sem virar `RuntimeError`."""
    pytest.importorskip("rapidocr")

    class MissingWeightError(Exception):
        pass

    def no_weights(_engine):
        raise MissingWeightError

    monkeypatch.setattr("rapidocr.main.RapidOCR._load_det_model", no_weights)
    with pytest.raises(MissingWeightError):
        PPOCR().prepare()


def test_a_session_that_fell_back_to_the_cpu_is_refused():
    _require_cuda(["CUDAExecutionProvider", "CPUExecutionProvider"])
    with pytest.raises(RuntimeError, match="onnxruntime-gpu"):
        _require_cuda(["CPUExecutionProvider"])


class _ResizeImgError(Exception):
    """Como o erro do RapidOCR que embrulha qualquer exceção do `cv2.resize`."""


class _Engine:
    """Um motor cujo pré-processamento falha com `cause` embrulhada, como o RapidOCR faz."""

    def __init__(self, cause: Exception | None) -> None:
        self.cause = cause

    def preprocess_img(self, _pixels):
        if self.cause is None:
            raise _ResizeImgError("resize_w or resize_h is less than or equal to 0")
        raise _ResizeImgError from self.cause


def _stubbed(cause: Exception | None) -> PPOCR:
    pytest.importorskip("rapidocr")
    reader = PPOCR()
    reader._engine = _Engine(cause)
    return reader


def test_a_broken_opencv_stops_the_document_and_names_the_packages():
    """Um `cv2` sem `resize` falharia em toda página: o documento para, em vez de voltar vazio."""
    reader = _stubbed(AttributeError("module 'cv2' has no attribute 'resize'"))
    with pytest.raises(ImportError, match="opencv-python-headless") as info:
        process(make_pdf(TEXT_CENTRAL), policy="all_cheap", cheap=[reader])
    assert "--force-reinstall" in str(info.value)


def test_an_image_that_does_not_resize_fails_only_its_page():
    with pytest.warns(RuntimeWarning, match="resize_w"):
        result = process(make_pdf(TEXT_CENTRAL), policy="all_cheap", cheap=[_stubbed(None)])
    assert result.spent.pages_cheap_failed == 1
