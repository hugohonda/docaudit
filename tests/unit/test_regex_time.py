"""Nenhuma forma de verificação pode travar numa linha longa que quase casa."""

from __future__ import annotations

import multiprocessing
import re

import pytest

from docaudit import policies
from docaudit.policies import Check

LIMIT_SECONDS = 2.0
NEAR_MATCHES = "".join(
    unit * (1000 // len(unit))
    for unit in (
        "A. B. C. ",
        "1234567890",
        "1.234.",
        "1 2 3 4 5 ",
        "1 de ",
        "R$ 1.234 ",
        "12/34/",
        "abcde fghij ",
        "12-34-",
        "123 456 ",
        "ABC DEF ",
    )
)
PATTERNS = {
    f"{name}.{field}": pattern
    for name, check in vars(policies).items()
    if isinstance(check, Check)
    for field in ("pattern", "labeled")
    if isinstance(pattern := getattr(check, field), re.Pattern)
}


@pytest.mark.parametrize("name", sorted(PATTERNS))
def test_a_check_scans_a_long_near_match_in_bounded_time(name):
    """O motor de regex segura o GIL: o teto só vale noutro processo, que pode ser morto."""
    worker = multiprocessing.get_context("fork").Process(
        target=PATTERNS[name].findall, args=(NEAR_MATCHES,)
    )
    worker.start()
    worker.join(LIMIT_SECONDS)
    hung = worker.is_alive()
    if hung:
        worker.kill()
        worker.join()
    assert not hung, f"{name} passou de {LIMIT_SECONDS} s"


def test_the_guard_sees_the_checks():
    """Sem padrões, os testes acima passariam sem conferir nada."""
    assert "CPF.pattern" in PATTERNS
