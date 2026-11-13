# Relação de nome e valor

A relação de pagamentos de um diário oficial, ou o anexo de um edital, é uma
tabela longa de nome, identificador e valor, muitas vezes digitalizada. A
etapa barata lê todas as páginas. Só a página em que a leitura barata
provou ter falhado vai ao leitor caro: a leitura vazia, o texto mal
decodificado, ou um CPF (Cadastro de Pessoas Físicas), CNPJ, número de
processo ou valor em dinheiro que não confere.
Ele lê por região e devolve cada tabela num trecho, uma linha de texto por
linha da tabela.

O leitor caro aqui é um modelo de visão e linguagem servido na sua máquina.
Como subir o servidor está em
[Ligar um modelo de visão e linguagem](../how-to/vlm.md).

```python
from docaudit import Budget, ModelCallCache, process
from docaudit.backends.layout import PPDocLayout
from docaudit.backends.vlm import VLM
from docaudit.policies import AMOUNT_BRL, fold_lookalikes

result = process(
    "edital.pdf",
    policy="evidence",
    budget=Budget(max_strong_fraction=0.1),
    strong=VLM(layout=PPDocLayout(), concurrency=4),
    cache=ModelCallCache(),
)

for chunk in result.chunks:
    if chunk.kind != "table":
        continue
    for line in chunk.text.splitlines():
        cells = [cell.strip() for cell in line.split(" | ")]
        amounts = [m.group(0) for m in AMOUNT_BRL.pattern.finditer(fold_lookalikes(line))]
        print(chunk.page, cells, amounts)
```

`fold_lookalikes` troca hífens, espaços e formas de largura total
tipográficos pelos equivalentes ASCII, sem mudar a posição de nenhum
caractere. A forma do valor casa no texto assim dobrado.

`chunk.kind == "table"` só aparece nos trechos do leitor por região. Nas
páginas que ficaram com a leitura barata, a tabela chega linha a linha, sem
separador de célula. Para agrupar essas linhas em fileiras pela posição das
caixas, use `result.records()`:

```python
from docaudit import process

result = process("edital.pdf")
for record in result.records():
    if record.tabular:
        for row in record.rows:
            print(record.ref, row)
```

Um valor que quebra entre duas linhas fica partido entre dois trechos. A
entidade dele sai uma vez, com as duas linhas em `chunk_ids`; veja
[Entidades padrão](../entities.md).

Para encaminhar também a página em que o valor não bate com o extenso entre
parênteses, acrescente `AMOUNT_IN_WORDS` à política, como em
[Declarar os campos do seu documento](../how-to/checks.md).
