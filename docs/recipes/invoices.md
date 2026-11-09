# Notas fiscais e boletos

A chave de acesso de uma nota fiscal, a linha digitável de um boleto e o
código de arrecadação de uma guia já saem em `Result.entities` por padrão.
Cada um traz o estado que os dígitos verificadores deram. Por padrão, eles não
encaminham a página ao leitor caro. Num lote de notas e boletos, em que uma
chave lida errada é o que mais importa, ponha-os na política:

```python
from docaudit import Budget, process
from docaudit.backends.ppocr import PPOCR
from docaudit.policies import (
    ARRECADACAO,
    BOLETO,
    DEFAULT_SIGNALS,
    NFE_KEY,
    EvidenceRouter,
    FailsCheck,
)

result = process(
    "notas.pdf",
    policy=EvidenceRouter([*DEFAULT_SIGNALS, *map(FailsCheck, (NFE_KEY, BOLETO, ARRECADACAO))]),
    budget=Budget(max_strong_pages=20),
    strong=PPOCR("v6-medium"),
)
for entity in result.entities:
    if entity.kind in {"chave de acesso", "linha digitável de boleto", "código de arrecadação"}:
        print(entity.page, entity.kind, entity.value, entity.state)
```

| campo | `kind` | regra |
|---|---|---|
| `NFE_KEY` | `chave de acesso` | os 44 dígitos de uma NF-e, CT-e ou NFC-e: dígito em módulo 11, UF do IBGE, mês e modelo |
| `BOLETO` | `linha digitável de boleto` | os 47 dígitos: o dígito de cada campo em módulo 10 e o geral em módulo 11 |
| `ARRECADACAO` | `código de arrecadação` | os 48 dígitos de uma guia ou conta: o dígito de cada bloco e o geral |

Um campo que a biblioteca não traz entra do mesmo jeito, como um `Check`
seu: veja [Declarar os campos do seu documento](../how-to/checks.md).
