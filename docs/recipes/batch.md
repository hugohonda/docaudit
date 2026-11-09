# Ler muitos processos em lote

Num lote, o paralelismo que rende é um processo do sistema operacional por
documento, com `PPOCR(threads=)` dividindo os núcleos entre eles. O porquê
está em [Implantar num serviço](../how-to/deploy.md).

Leitores, cache e documento aberto não passam de um processo a outro. O macOS,
e o Linux a partir do Python 3.14, iniciam cada processo do zero, e cada um
monta os seus. O primeiro documento vai sozinho, antes do pool, para que um
processo só baixe os pesos.

```python
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from docaudit import ModelCallCache, process
from docaudit.backends.ppocr import PPOCR

CACHE = Path("cache/docaudit.sqlite")
OUT = Path("saida")
PROCESSES = 4
THREADS = max(1, (os.cpu_count() or 1) // PROCESSES)


def read_one(pdf: Path) -> str:
    # Uma conexão por processo, no mesmo arquivo; a segunda execução do lote
    # lê do cache.
    cache = ModelCallCache(CACHE)
    try:
        result = process(
            pdf,
            policy="evidence",
            cheap=["text_layer", PPOCR(threads=THREADS)],
            cache=cache,
        )
    finally:
        cache.close()
    (OUT / f"{pdf.stem}.json").write_text(result.model_dump_json())
    return pdf.name


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    CACHE.parent.mkdir(exist_ok=True)
    case_files = sorted(Path("autos").glob("*.pdf"))
    # O primeiro documento vai sozinho: os pesos são baixados uma vez, antes do pool.
    print("pronto:", read_one(case_files[0]))
    with ProcessPoolExecutor(max_workers=PROCESSES) as pool:
        for name in pool.map(read_one, case_files[1:]):
            print("pronto:", name)
```

Sem `strong=`, a política `evidence` só registra, no JSON de cada documento,
que páginas o leitor caro leria. Para ligá-lo, com um teto por documento,
veja [Escalar só o que falhou](../how-to/escalate.md).

Com uma GPU, o mesmo lote usa `PPOCR(engine="cuda")` em poucos processos que
dividem a placa. `threads=` continua dividindo a CPU entre eles. Se faltar
memória na placa, algumas páginas falham. A página que falha não some: a
decisão dela traz a mensagem em `failures`, e `incomplete` diz que nenhum
outro leitor leu no lugar. Reduza o número de processos até que nenhuma
página falhe.

Sem GPU, o extra `openvino` faz o PP-OCR ler o mesmo lote na CPU mais
depressa, com o mesmo texto. Veja [Instalação](../install.md).
