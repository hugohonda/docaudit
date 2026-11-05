from docaudit.cache import ModelCallCache, call_key


def test_key_is_deterministic_and_input_sensitive():
    a = call_key("doc", 3, 200, "ppocr", "v1")
    assert a == call_key("doc", 3, 200, "ppocr", "v1")
    assert a != call_key("doc2", 3, 200, "ppocr", "v1")
    assert a != call_key("doc", 4, 200, "ppocr", "v1")
    assert a != call_key("doc", 3, 300, "ppocr", "v1"), "outro DPI, outros pixels"
    assert a != call_key("doc", 3, 200, "tesseract", "v1")


def test_roundtrip(tmp_path):
    cache = ModelCallCache(tmp_path / "c.sqlite")
    cache.put("k", "ppocr", "v1", {"text": "olá"})
    assert cache.get("k") == {"text": "olá"}
    assert len(cache) == 1
    cache.close()


def test_a_path_given_as_str_opens_the_same_file(tmp_path):
    cache = ModelCallCache(str(tmp_path / "c.sqlite"))
    cache.put("k", "ppocr", "v1", {"text": "olá"})
    cache.close()
    cache = ModelCallCache(tmp_path / "c.sqlite")
    assert cache.get("k") == {"text": "olá"}
    cache.close()


def test_threads_share_one_connection_without_tripping_sqlite(tmp_path):
    """`workers > 1` leva o cache a várias threads; uma conexão sem lock dá InterfaceError."""
    from concurrent.futures import ThreadPoolExecutor

    cache = ModelCallCache(tmp_path / "c.sqlite")

    def hammer(i: int) -> dict[str, object] | None:
        for _ in range(50):
            cache.put(f"k{i}", "fake", "v1", {"i": i})
            cache.get(f"k{(i + 1) % 8}")
        return cache.get(f"k{i}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(hammer, range(8))) == [{"i": i} for i in range(8)]
    assert len(cache) == 8
    cache.close()


def test_output_version_changes_the_key():
    """Mesmo leitor, outra versão do que produz: a entrada antiga não serve."""
    assert call_key("doc", 0, 200, "ppocr", "v1") != call_key("doc", 0, 200, "ppocr", "v2")


def test_schema_digest_tracks_the_chunk_model():
    """O digest vem dos campos de `Chunk`, não de uma constante a lembrar."""
    from pydantic import BaseModel

    from docaudit.types import SCHEMA_HEX_CHARS, chunk_schema_digest

    d = chunk_schema_digest()
    assert len(d) == SCHEMA_HEX_CHARS
    assert d == chunk_schema_digest(), "tem de ser estável entre chamadas"

    # Reproduz a conta com um modelo de campos diferentes: o digest tem de mudar.
    import hashlib

    class Outro(BaseModel):
        id: str

    campos = ";".join(f"{n}:{f.annotation}" for n, f in sorted(Outro.model_fields.items()))
    assert hashlib.sha256(campos.encode()).hexdigest()[:SCHEMA_HEX_CHARS] != d


def test_schema_digest_is_in_the_key(monkeypatch):
    """Mudar o esquema de Chunk invalida tudo, sem ninguém bumpar nada."""
    from docaudit import cache as cache_mod

    before = call_key("doc", 0, 200, "ppocr", "v1")
    monkeypatch.setattr(cache_mod, "chunk_schema_digest", lambda: "esquema-novo")
    assert call_key("doc", 0, 200, "ppocr", "v1") != before


def test_opening_waits_for_another_process_holding_the_file(tmp_path):
    """Mudar para WAL pede o arquivo só para si; o SQLite recusa na hora em vez de esperar."""
    import sqlite3
    import threading

    path = tmp_path / "c.sqlite"
    other = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    other.execute("CREATE TABLE t (x)")
    other.execute("BEGIN")
    other.execute("SELECT * FROM t").fetchall()
    release = threading.Timer(0.1, lambda: other.execute("COMMIT"))
    release.start()

    cache = ModelCallCache(path)
    release.join()
    check = sqlite3.connect(path)
    assert check.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    check.close()
    cache.put("k", "ppocr", "v1", {"text": "olá"})
    assert cache.get("k") == {"text": "olá"}
    cache.close()
    other.close()
