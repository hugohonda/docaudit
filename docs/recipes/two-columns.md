# Diário oficial em duas colunas

Um motor de reconhecimento óptico de caracteres (OCR) que lê por linha devolve as linhas pela altura na página. Numa página em duas
colunas, isso intercala as colunas: a linha de um valor aparece seguida da
linha de um endereço da outra coluna. O detector de layout põe cada linha no
bloco que a contém e devolve os blocos na ordem de leitura.

```python
from docaudit import process
from docaudit.backends.layout import PPDocLayout

result = process("diario.pdf", layout=PPDocLayout(drop=()))
print(result.to_markdown())
```

`drop=()` mantém todos os blocos, inclusive cabeçalho, rodapé e a tarja da
margem. Para ordenar a leitura, toda linha precisa de um bloco. Sem ele, a
linha vai ao bloco mais próximo e sai fora do lugar.

Cada linha ganha o rótulo do bloco em `Chunk.kind`, como `text`,
`paragraph_title` ou `table`. O detector roda uma vez por página, na mesma
renderização da leitura, e o tempo dele entra nos segundos da etapa que
renderizou a página. Os pesos baixam na primeira detecção.

O porquê de ordenar por blocos está em
[Cascata e elementos fixos](../concepts/cascade.md). Os parâmetros de
`PPDocLayout` estão em [Configuração](../configuration.md).
