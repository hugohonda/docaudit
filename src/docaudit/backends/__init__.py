"""Os leitores que acompanham o pacote, um por extra, e o que eles partilham."""

from __future__ import annotations

import os

__all__ = ["process_cpus"]


def process_cpus() -> int | None:
    """Os núcleos disponíveis ao processo, quando são menos que os da máquina; senão None.

    `os.process_cpu_count` respeita a afinidade do processo, que um contêiner
    com `cpuset` restringe; o motor de inferência conta os núcleos da
    máquina e abriria threads a mais. A cota de CPU de um contêiner sem
    `cpuset` não aparece em lugar nenhum: nesse caso, quem chama passa o
    número em `threads=`. None deixa o padrão do motor.
    """
    available = getattr(os, "process_cpu_count", os.cpu_count)()
    total = os.cpu_count()
    if available is None or total is None or available >= total:
        return None
    return available
