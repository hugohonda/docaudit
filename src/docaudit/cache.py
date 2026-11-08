# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Cache endereçado por conteúdo das leituras de página.

A chave identifica a página pelo hash do documento, o índice e o DPI, e o
leitor pelo nome e pela versão do que produz. Nenhum pixel entra na chave: o
documento e o DPI determinam a renderização, e assim a consulta não custa uma
renderização que a leitura talvez nem fizesse. Com isso uma reexecução é
gratuita.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from docaudit.types import chunk_schema_digest

__all__ = ["ModelCallCache", "call_key", "default_cache_path"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reads (
    key        TEXT PRIMARY KEY,
    reader     TEXT NOT NULL,
    version    TEXT NOT NULL,
    payload    TEXT NOT NULL,
    created_at REAL NOT NULL DEFAULT (julianday('now'))
);
"""


def default_cache_path() -> Path:
    """Onde o cache grava quando nenhum caminho é dado.

    `DOCAUDIT_CACHE_DIR` sobrescreve, lido na hora da chamada.
    """
    root = os.environ.get("DOCAUDIT_CACHE_DIR")
    base = Path(root) if root else Path.home() / ".cache" / "docaudit"
    return base / "calls.sqlite"


def call_key(
    doc_id: str, page: int, dpi: int, reader: str, output_version: str, region: str = ""
) -> str:
    """Chave determinística da leitura de uma página por um leitor.

    Entram cinco componentes mais um derivado. O hash do documento, o índice e
    o DPI são a entrada: juntos determinam os pixels. O nome do leitor e o
    `output_version` são quem leu e como: pesos, idioma, prompt e formato de
    saída. E o digest do esquema de `Chunk`, que não é parâmetro: vem do
    próprio modelo de dados e muda quando o que se guarda muda de forma.

    Uma região da página, quando é ela que se lê, entra como mais um
    componente.

    A versão e o digest evitam a falha silenciosa: sem eles, uma entrada
    gravada num formato continua sendo lida depois de o formato mudar, e o
    Pydantic preenche o que falta por omissão.
    """
    raw = f"{doc_id}|{page}|{dpi}|{reader}|{output_version}|{chunk_schema_digest()}"
    if region:
        raw += f"|region={region}"
    return hashlib.sha256(raw.encode()).hexdigest()


_WAIT_SECONDS = 30.0
"""Quanto um processo espera outro terminar de gravar no mesmo arquivo.

Não calibrado: cada gravação é uma leitura de página, e dura muito menos.
"""


def _enter_wal(conn: sqlite3.Connection) -> None:
    """Põe o arquivo em modo WAL, esperando os outros processos que o abrem junto.

    Mudar o modo do journal pede o arquivo só para si, e o SQLite recusa na
    hora, sem a espera que dá às gravações, quando outro processo o tem
    aberto. Isso só acontece enquanto o arquivo é criado: o modo WAL fica
    gravado nele, e depois o pedido não muda nada. Tenta de novo até
    `_WAIT_SECONDS`.
    """
    deadline = time.monotonic() + _WAIT_SECONDS
    while True:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


class ModelCallCache:
    """Cache em SQLite, seguro para reexecução e partilhado por threads e por processos."""

    def __init__(self, path: Path | str | None = None) -> None:
        """Abre (ou cria) o SQLite em `path`. Sem `path`, usa `default_cache_path()`."""
        path = Path(path) if path is not None else default_cache_path()
        self.path = path
        # Uma conexão, partilhada pelas threads do tier barato. O sqlite3 do
        # Python não serializa chamadas concorrentes numa mesma conexão: duas
        # threads num `execute` ao mesmo tempo dão `InterfaceError`.
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = sqlite3.connect(
            path, timeout=_WAIT_SECONDS, check_same_thread=False
        )
        # WAL e synchronous=NORMAL: cada leitura é um commit, e um commit
        # durável com fsync de journal por página é caro para gravar dado
        # que por definição é regenerável. O WAL também deixa um processo
        # ler enquanto outro grava.
        _enter_wal(self._conn)
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)

    def get(self, key: str) -> dict[str, object] | None:
        """Devolve o payload salvo, ou None em miss."""
        if self._conn is None:
            return None
        with self._lock:
            row = self._conn.execute("SELECT payload FROM reads WHERE key = ?", (key,)).fetchone()
        return None if row is None else json.loads(row[0])

    def put(self, key: str, reader: str, version: str, payload: dict[str, object]) -> None:
        """Grava um payload."""
        if self._conn is None:
            return
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO reads (key, reader, version, payload) VALUES (?, ?, ?, ?)",
                (key, reader, version, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            )
            self._conn.commit()

    def __len__(self) -> int:
        """Número de leituras guardadas."""
        if self._conn is None:
            return 0
        with self._lock:
            return int(self._conn.execute("SELECT count(*) FROM reads").fetchone()[0])

    def close(self) -> None:
        """Fecha a conexão SQLite."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
