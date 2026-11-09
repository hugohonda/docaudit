# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Leitura de documentos digitalizados, com verificação da leitura e a origem de cada trecho.

Tudo o que não está em `__all__` é privado e pode mudar sem aviso.
"""

from __future__ import annotations

from docaudit.cache import ModelCallCache
from docaudit.pdf import PageView, doc_id_for
from docaudit.process import Reread, TrustLayer, mark_furniture, process
from docaudit.registry import get_backend
from docaudit.session import Document, Doubt
from docaudit.types import (
    BBox,
    Budget,
    Chunk,
    DocumentError,
    DocumentFacts,
    Entity,
    EntityState,
    ExternalBackendError,
    Figure,
    Folha,
    Layout,
    Metered,
    OtherReading,
    Page,
    PageDimensions,
    Piece,
    Reader,
    Record,
    Region,
    Result,
    RoutingDecision,
    Run,
    Signature,
    Spent,
    Stamp,
    Substrate,
    Tier,
    TriagePolicy,
)
from docaudit.visualize import visualize

try:
    from docaudit._version import __version__
except ImportError:  # pragma: no cover - árvore de fonte sem build
    __version__ = "0.0.0.dev0"

__all__ = [
    "BBox",
    "Budget",
    "Chunk",
    "Document",
    "DocumentError",
    "DocumentFacts",
    "Doubt",
    "Entity",
    "EntityState",
    "ExternalBackendError",
    "Figure",
    "Folha",
    "Layout",
    "Metered",
    "ModelCallCache",
    "OtherReading",
    "Page",
    "PageDimensions",
    "PageView",
    "Piece",
    "Reader",
    "Record",
    "Region",
    "Reread",
    "Result",
    "RoutingDecision",
    "Run",
    "Signature",
    "Spent",
    "Stamp",
    "Substrate",
    "Tier",
    "TriagePolicy",
    "TrustLayer",
    "__version__",
    "doc_id_for",
    "get_backend",
    "mark_furniture",
    "process",
    "visualize",
]
