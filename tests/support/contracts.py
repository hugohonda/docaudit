"""Suítes de contrato por Protocol.

Herde e forneça a fixture `reader`. Vale para leitores dos dois tiers, porque
o contrato é um só.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from docaudit.types import Chunk, Reader

if TYPE_CHECKING:
    from docaudit.pdf import PageView

__all__ = ["ReaderContract"]


@pytest.mark.contract
class ReaderContract:
    """O que todo `Reader` tem de cumprir, além da forma do Protocol."""

    @pytest.fixture
    def reader(self) -> Reader:
        raise NotImplementedError("defina a fixture `reader` na subclasse")

    def test_satisfies_protocol(self, reader: Reader) -> None:
        assert isinstance(reader, Reader)
        assert reader.name
        assert isinstance(reader.external, bool)
        assert isinstance(reader.output_version, str)
        assert reader.output_version

    def test_chunks_are_within_page(self, reader: Reader, scanned_view: PageView) -> None:
        for c in reader.read(scanned_view):
            assert 0.0 <= c.bbox.x0 <= c.bbox.x1 <= 1.0
            assert 0.0 <= c.bbox.y0 <= c.bbox.y1 <= 1.0
            assert c.page == scanned_view.page.index
            assert c.source == reader.name

    def test_ids_are_content_addressed(self, reader: Reader, scanned_view: PageView) -> None:
        a = [c.id for c in reader.read(scanned_view)]
        b = [c.id for c in reader.read(scanned_view)]
        assert a == b
        assert len(set(a)) == len(a)

    def test_blank_page_yields_no_text(self, reader: Reader, blank_view: PageView) -> None:
        assert all(not c.text.strip() for c in reader.read(blank_view))

    def test_confidence_in_unit_interval(self, reader: Reader, scanned_view: PageView) -> None:
        for c in reader.read(scanned_view):
            assert c.confidence is None or 0.0 <= c.confidence <= 1.0

    def test_chunks_roundtrip_json(self, reader: Reader, scanned_view: PageView) -> None:
        for c in reader.read(scanned_view):
            assert Chunk.model_validate_json(c.model_dump_json()) == c
