# Tarja e folha de outro sistema

A tarja é a faixa que o sistema eletrônico do tribunal imprime na margem de
cada página, com o código do documento e a assinatura. A folha é o número
carimbado na página dos autos, que não coincide com o índice da página.

Por padrão, `Page.stamp` procura a tarja do e-SAJ, e `Page.folha` o carimbo
`fls. N`. Os outros sistemas imprimem outra coisa, e cada um entra pelo nome
do formato:

```python
from docaudit import process

result = process(
    "autos.pdf",
    stamps=["e-saj", "pje", "projudi-pr", "projudi-go", "eproc"],
    folhas=["folha", "pagina-projudi"],
)
for page in result.pages:
    print(page.index, page.stamp.code if page.stamp else None, page.folha)
for piece in result.pieces():
    print(piece.code, piece.pages)
```

| nome | sistema | o que vira `code` |
|---|---|---|
| `e-saj` | e-SAJ, de São Paulo e de outros tribunais | o código de conferência |
| `pje` | PJe | o número do documento |
| `projudi-pr` | Projudi do TJPR | o identificador da validação |
| `projudi-go` | Projudi do TJGO | o código de localização |
| `eproc` | eproc | o evento e o anexo |

Fora o `e-saj`, os formatos são pontos de partida: confira-os nos seus autos
antes de confiar neles. `pagina-projudi` lê a página do processo no pé do
Projudi. No eproc, a `Página` do rodapé é a do anexo, e ela não é folha.

## Um sistema próprio

Um formato próprio de tarja é um `StampFormat`. A expressão regular precisa
do grupo `code`. Os grupos `process`, `signer`, `date`, `time` e `protocol`
são opcionais. Uma forma própria de folha é um `Check` com o número no grupo
`number`:

```python
import re

from docaudit import process
from docaudit.policies import Check, StampFormat

MY_STAMP = StampFormat(
    "meu-sistema",
    re.compile(
        r"Assinado em (?P<date>\d{2}/\d{2}/\d{4}) (?P<time>\d{2}:\d{2}:\d{2}) .* Doc\. (?P<code>\d+)"
    ),
    time_format="%H:%M:%S",
    process_check=None,  # a tarja não traz número CNJ
)
PAGE_NUMBER = Check("pagina", re.compile(r"Folha (?P<number>\d+)"), lambda _: True)

result = process("autos.pdf", stamps=[MY_STAMP], folhas=[PAGE_NUMBER])
```

`process_check` confere o número do processo que a tarja traz, pelo dígito do padrão do
Conselho Nacional de Justiça (CNJ). Uma tarja cujo número não confere não é tratada como tarja. Passe `None`
quando a tarja do seu sistema não traz o número.

As páginas seguidas com o mesmo `code` formam uma peça, em
`result.pieces()`.
