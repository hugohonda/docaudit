# Ler com o Azure como última etapa

O leitor `AzureRead` manda a página ao modelo de leitura do Azure AI Document
Intelligence e devolve uma linha por trecho, com a caixa de cada uma. É um
[leitor externo](../glossary.md#externo): a página sai da máquina. Serve de
[leitor caro](../glossary.md#leitor-caro) para a página que a leitura barata
não leu.

!!! warning "A página sai da máquina"
    `process()` recusa o `AzureRead` com `ExternalBackendError` até receber
    `allow_external=True`. Com essa autorização, cada página encaminhada vai
    ao serviço, como imagem. Leia [Segurança dos dados](../security.md) antes
    de mandar um documento com dados pessoais.

Não há o que instalar: o leitor fala com o serviço pela biblioteca padrão do
Python. Ele precisa do endereço e da chave de um recurso do Document
Intelligence, e entra como instância, e não pelo nome.

```python
import os

from docaudit import Budget, process
from docaudit.backends.azure import AzureRead
from docaudit.policies import EmptyRead, EvidenceRouter, UnreadLines

reader = AzureRead(
    os.environ["AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT"],
    os.environ["AZURE_DOCUMENT_INTELLIGENCE_KEY"],
    price_per_page=PRICE,  # o preço por página do seu contrato, em dólares
)
result = process(
    "documento-publico.pdf",
    policy=EvidenceRouter([EmptyRead(), UnreadLines()]),
    strong=reader,
    allow_external=True,
    budget=Budget(max_strong_pages=20),
)
print(result.read_by())
print(result.spent.calls, result.spent.usd)
```

A leitura barata lê o documento inteiro na máquina. Com os dois sinais do
exemplo, só sai a página vazia e a página com mais linhas detectadas do que
lidas. Com os sinais padrão de `evidence`, sai também a página com um valor
que falha a regra ou com texto mal decodificado. `Budget` limita quantas
páginas vão ao serviço.

| parâmetro | para que serve |
|---|---|
| `endpoint` | o endereço do recurso, como `https://<recurso>.cognitiveservices.azure.com` |
| `api_key` | a chave do recurso |
| `model` | o modelo de análise; `prebuilt-read` por padrão |
| `api_version` | a versão da API do serviço |
| `price_per_page` | dólares por página, para `Result.spent.usd` ter valor. A biblioteca não traz tabela de preços |
| `timeout` | segundos por pedido, e o tempo que a leitura tem para terminar |
| `retries` | quantas vezes repetir um pedido que o serviço recusou por carga |

## O que o leitor devolve

- **Um trecho por linha**, na ordem em que o serviço as devolve. A caixa é a
  envoltória do polígono da linha, no sistema da imagem.
- **A confiança da linha** é a menor entre as palavras dela. O serviço dá
  confiança por palavra, e não por linha.
- **O giro é da linha.** O serviço lê sozinho a página girada. Na folha de
  cabeça para baixo, o corpo sai com `turn=180` e o carimbo aposto em pé com
  `turn=0`. `Chunk.as_read()` dá a caixa como a linha é lida.
- **O texto é o que o serviço leu**, sem correção. Quando ele lê `R$` como
  `RS`, o valor sai assim: a regra do valor em reais aceita as duas grafias.

O leitor manda a imagem que a biblioteca renderizou, e não o PDF: o serviço
lê os pixels, sem depender da camada de texto do arquivo. Com
`reread="region"`, vai só o recorte das linhas que falharam, e o serviço
cobra cada recorte como uma página.

## Quando o serviço falha

| o que acontece | o que o leitor faz |
|---|---|
| HTTP 429 ou 5xx, tempo esgotado, conexão caída | repete `retries` vezes, seguindo o `Retry-After`; depois, a página falha |
| a leitura termina como falha, ou não termina em `timeout` | a página falha |
| a chave é recusada (401 ou 403) | levanta `PermissionError` e interrompe o documento |

A página que falha fica com a leitura barata. `Result.review()` a lista com
`reader_failed`, e `RoutingDecision.failures` traz a mensagem do serviço.

`Result.spent.calls` conta as imagens enviadas. Uma leitura servida pelo
[cache](../glossary.md#cache) não é enviada de novo e não conta.
