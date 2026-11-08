"""Apoio da suíte: suíte de contrato, dublês e construtores de PDF."""

from tests.support.contracts import ReaderContract
from tests.support.doubles import FakeLayout, FakeVLM
from tests.support.fixtures import make_page, make_pdf, make_scanned_pdf

__all__ = ["FakeLayout", "FakeVLM", "ReaderContract", "make_page", "make_pdf", "make_scanned_pdf"]
