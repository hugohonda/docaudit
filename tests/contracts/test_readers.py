"""Os leitores do núcleo passam pela mesma suíte de contrato que os demais."""

from __future__ import annotations

import pytest
from tests.support.contracts import ReaderContract

from docaudit.backends.textlayer import TextLayerReader


class TestTextLayerContract(ReaderContract):
    @pytest.fixture
    def reader(self):
        return TextLayerReader()
