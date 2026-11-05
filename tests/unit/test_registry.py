import pytest

from docaudit import registry
from docaudit.registry import get_backend


def test_unknown_backend_names_what_is_installed():
    with pytest.raises(LookupError, match="não encontrado"):
        get_backend("nao-existe")


def test_missing_optional_dependency_names_the_extra(monkeypatch):
    # Um entry point declarado cujo módulo não importa: o registry traduz o
    # ImportError em "instale o extra", nomeando o extra pelo nome do backend.
    class _FailingEntryPoint:
        name = "needs-wheels"

        def load(self):
            raise ImportError("No module named 'wheels'")

    monkeypatch.setattr(registry, "entry_points", lambda group: [_FailingEntryPoint()])
    with pytest.raises(ImportError, match=r"docaudit\[needs-wheels\]"):
        get_backend("needs-wheels")


def test_implemented_backend_resolves():
    from docaudit.backends.tesseract import TesseractOCR

    assert get_backend("tesseract") is TesseractOCR
