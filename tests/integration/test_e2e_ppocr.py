"""Ponta a ponta com o PP-OCRv5 de verdade no tier caro.

Marcado `slow` porque baixa os pesos na primeira execução. Roda com
`uv run pytest -m slow`.

O que este arquivo cobre e os testes com dublês não cobrem: que a política
`evidence` manda ao modelo a página que a leitura barata não leu, que o modelo
devolve português com acentos, e que a leitura cara substitui a barata no
resultado.
"""

from __future__ import annotations

from typing import get_args

import pytest
from tests.support.fixtures import make_notice_pdf, make_pdf

import docaudit
from docaudit import Tier

pytestmark = [pytest.mark.slow, pytest.mark.integration]

pytest.importorskip("rapidocr", reason="precisa do extra `ppocr`")

from tests.support import ReaderContract  # noqa: E402

from docaudit.backends import ppocr  # noqa: E402
from docaudit.backends.ppocr import PPOCR, Models  # noqa: E402
from docaudit.cache import default_cache_path  # noqa: E402

ACCENTED = (
    "TERMO DE AUDIÊNCIA DE CONCILIAÇÃO Nº 3",
    "Requerente: José Conceição Araújo",
    "Valor cedido: R$ 18.557,07",
)


class EmptyReader:
    """Uma cascata barata que não lê nada: a página volta vazia."""

    name = "vazio"
    external = False
    output_version = "v1"

    def read(self, view):
        del view
        return []


@pytest.mark.parametrize("models", get_args(Models))
def test_evidence_sends_an_unread_scan_to_ppocr_and_keeps_its_read(models) -> None:
    result = docaudit.process(
        make_notice_pdf(ACCENTED),
        policy="evidence",
        cheap=[EmptyReader()],
        strong=PPOCR(models=models),
    )

    assert [d.tier for d in result.decisions] == [Tier.STRONG]
    assert "vazia" in result.decisions[0].reason
    assert {c.source for c in result.chunks} == {f"ppocr-{models}"}

    text = "\n".join(c.text for c in result.chunks)
    assert "CONCILIAÇÃO" in text, f"o acento se perdeu: {text!r}"
    assert "Conceição" in text
    assert "18.557,07" in text

    ys = [c.bbox.y0 for c in sorted(result.chunks, key=lambda c: c.reading_order or 0)]
    assert ys == sorted(ys), "a ordem de leitura desce a página"
    assert all(c.confidence is not None for c in result.chunks)


# Uma linha escrita de baixo para cima na margem direita, como a tarja do e-SAJ.
STRIP = (
    "BT /F1 14 Tf 100 700 Td (CERTIDAO DE OBJETO E PE) Tj ET\n"
    "BT /F1 12 Tf 0 1 -1 0 570 120 Tm (informe o processo 9004884-76.2017.8.26.0533) Tj ET"
)


def test_a_line_written_bottom_to_top_is_read_upright() -> None:
    result = docaudit.process(make_pdf(STRIP), cheap=[PPOCR()])
    texts = [c.text for c in result.chunks]
    assert any("9004884-76.2017.8.26.0533" in t for t in texts), texts
    assert any("CERTIDAO" in t for t in texts), texts


def test_an_own_recognizer_is_loaded_from_its_file(tmp_path) -> None:
    stock = docaudit.process(make_notice_pdf(ACCENTED), cheap=[PPOCR()])
    # O reconhecedor de fábrica, lido do arquivo: a leitura sai igual e o
    # nome traz o hash. O ONNX de fábrica grava o dicionário, que vence o
    # arquivo de `keys`.
    rec = default_cache_path().parent / "models" / "latin_PP-OCRv5_rec_mobile.onnx"
    keys = tmp_path / "keys.txt"
    keys.write_text("a\nb\n")
    own = PPOCR(rec=rec, keys=keys)
    result = docaudit.process(make_notice_pdf(ACCENTED), cheap=[own])

    assert [c.text for c in result.chunks] == [c.text for c in stock.chunks]
    assert {c.source for c in result.chunks} == {own.name}
    assert own.name.startswith("ppocr-v5-latin+")


class TestPPOCRContract(ReaderContract):
    """A suíte de contrato sobre o motor real, em cada conjunto de pesos."""

    @pytest.fixture(params=get_args(Models))
    def reader(self, request):
        return PPOCR(models=request.param)


@pytest.mark.parametrize("models", get_args(Models))
def test_openvino_reads_the_same_lines_as_onnxruntime(models) -> None:
    pytest.importorskip("openvino", reason="precisa do extra openvino")
    pdf = make_notice_pdf(ACCENTED)
    onnx = docaudit.process(pdf, cheap=[PPOCR(models=models)])
    ov = docaudit.process(pdf, cheap=[PPOCR(models=models, engine="openvino")])

    assert [c.text for c in ov.chunks] == [c.text for c in onnx.chunks]
    # O pós-processamento do detector arredonda um pouco diferente: a borda da
    # caixa pode andar um pixel ou dois, o texto não.
    for a, b in zip(ov.chunks, onnx.chunks, strict=True):
        assert (a.bbox.x0, a.bbox.y0, a.bbox.x1, a.bbox.y1) == pytest.approx(
            (b.bbox.x0, b.bbox.y0, b.bbox.x1, b.bbox.y1), abs=0.003
        )


def test_a_gpu_session_that_fell_to_the_cpu_fails_once_and_stays_failed(monkeypatch) -> None:
    """Sem GPU, o ONNX Runtime cai na CPU; o leitor falha e não remonta o motor."""
    import onnxruntime

    if "CUDAExecutionProvider" in onnxruntime.get_available_providers():
        pytest.skip("com GPU, a sessão fica no CUDA")
    built = []
    real = ppocr._require_cuda
    monkeypatch.setattr(ppocr, "_require_cuda", lambda p: (built.append(p), real(p)))
    reader = PPOCR(engine="cuda")
    for _ in range(2):
        with pytest.raises(RuntimeError, match="onnxruntime-gpu"):
            reader._load()
    assert len(built) == 1
