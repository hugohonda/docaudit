"""Um documento público de verdade, baixado sob demanda e cacheado.

Nenhum PDF entra no repositório: o que se versiona é a URL. É um documento
nativo digital de 39 páginas, com capa esparsa, corpo denso e imagens soltas
entre o texto: a variedade que um documento sintético não produz sozinho.

Se a rede não estiver disponível, os testes pulam.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest

FILENAME = "tjba-digitalizacao.pdf"
URL = "https://www.tjba.jus.br/portal/wp-content/uploads/2021/04/TR-Digitalizacao.pdf"


@pytest.fixture(scope="session")
def real_document() -> Path:
    """O PDF público, baixado na primeira vez e reaproveitado depois."""
    root = os.environ.get("DOCAUDIT_TEST_CACHE")
    target = (Path(root) if root else Path(__file__).parent / ".pdfs") / FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)

    if not target.exists():
        try:
            with urllib.request.urlopen(URL, timeout=30) as response:
                content_bytes = response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            pytest.skip(f"sem rede para baixar {FILENAME}: {exc}")
        if not content_bytes.startswith(b"%PDF"):
            pytest.skip(f"{FILENAME} não voltou como PDF")
        target.write_bytes(content_bytes)

    return target
