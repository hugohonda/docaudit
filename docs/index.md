# docaudit

Leitura de documentos digitalizados em português do Brasil, com verificação
da leitura e a origem de cada trecho.

Um auto judicial tem centenas ou milhares de páginas, boa parte delas imagem
de papel escaneado. Um OCR simples é rápido e local, mas um número
lido errado continua parecendo certo. `docaudit` lê todas as páginas com um
leitor barato e confere a leitura com regras que o documento permite checar
sem conhecer o texto correto: o dígito verificador de um CPF, de um CNPJ ou
de um número de processo, a grafia de um valor em reais. A linha que falha é
relida por outra família de OCR, que separa o erro impresso no documento do
erro de leitura. Só o que continua sem explicação vai a um leitor caro. Cada
trecho devolvido diz de que página e de que posição saiu e qual leitor o
produziu. O caso principal são os autos judiciais; qualquer campo com forma
impressa e regra de validade entra como verificação própria.

O que ela não faz: não extrai campos de um tipo de documento, não decide
nada por modelo de linguagem e não segmenta o auto em peças. Ela entrega a
leitura em quatro níveis de custo, das entidades à imagem da página, para
que quem a chama, pessoa ou agente, decida com cada conclusão presa à linha
de origem ([Análise por um agente](agent.md)).

```python
import docaudit
from docaudit import Budget
from docaudit.backends.ppocr import PPOCR

result = docaudit.process(
    "autos.pdf",
    policy="evidence",  # (1)
    strong=PPOCR("v6-medium"),  # (2)
    budget=Budget(max_strong_fraction=0.1),  # (3)
)
```

1. Escala só a página cuja leitura barata falhou numa verificação.
2. O leitor caro é um `Reader` como os baratos: um OCR maior, um modelo de
   visão e linguagem local ou um serviço que você autorizar.
3. Teto opcional, em páginas. Sem evidência de falha, a política não escala
   nada. Tempo, tokens e dólares são relatados em `result.spent`, não
   limitados.

## Escolha o seu caminho

| se você quer | leia |
|---|---|
| ler o primeiro documento | [Começando](getting-started.md) |
| entender o que a biblioteca decide por você | [Conceitos](concepts.md) |
| saber exatamente o que volta | [Formato da resposta](response.md) |
| saber que valores ela acha, o que cada estado prova, e declarar os campos do seu tipo de documento | [Entidades](entities.md) |
| entregar a leitura a um modelo ou a uma pessoa, com cada conclusão presa à linha de origem | [Análise por um agente](agent.md) |
| ajustar leitores, política, verificações próprias, teto e servidores | [Configuração](configuration.md) |
| resolver um caso concreto: relação de nome e valor, diário em colunas, máscara de CPF, agente, lote | [Receitas](recipes.md) |
| ligar o seu motor de OCR | [Escrevendo um leitor](writing-a-reader.md) |
| saber o custo de cada etapa e o porquê dos padrões | [Desempenho](performance.md) |
| saber onde ela falha | [Limites](limits.md) |
| saber o que sai da máquina | [Segurança dos dados](security.md) |
| comparar com Docling, Marker, olmOCR e LlamaParse | [Comparação](comparison.md) |
| a API gerada das docstrings | [Referência](reference/docaudit.md) |

!!! warning "Estado"
    Alpha. Nada publicado no PyPI ainda, e a API pode mudar.
