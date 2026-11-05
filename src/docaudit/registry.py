"""Descoberta de backends por entry points.

Entry points permitem que um terceiro publique `docaudit-surya` no PyPI e, ao
instalá-lo, `cheap=["text_layer", "surya"]` passe a funcionar sem que a
biblioteca saiba da existência dele. Um leitor que não está instalado como
pacote entra como instância: `cheap=["text_layer", MeuLeitor()]`.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from docaudit.types import Reader

__all__ = ["get_backend"]

_GROUP = "docaudit.backends"


def get_backend(name: str) -> type[Reader]:
    """Resolve um backend pelo nome.

    Raises:
        LookupError: nome desconhecido.
        ImportError: backend conhecido, mas sem as dependências opcionais.
    """
    declared = {ep.name: ep for ep in entry_points(group=_GROUP)}
    if name not in declared:
        known = sorted(declared)
        raise LookupError(f"backend {name!r} não encontrado; instalados: {known}")
    try:
        # O entry point devolve `Any`; o contrato é conferido em `resolve`, na instância.
        return cast("type[Reader]", declared[name].load())
    except ImportError as exc:
        raise ImportError(
            f"backend {name!r} precisa de dependências opcionais; tente `uv add 'docaudit[{name}]'`"
        ) from exc
