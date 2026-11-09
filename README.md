# docaudit

Documentação: <https://hugohonda.github.io/docaudit/>

Leitura de documentos digitalizados em português do Brasil, com conferência
da leitura e a origem de cada trecho.

`docaudit` lê todas as páginas com um leitor barato e confere o que leu com
regras que o próprio documento traz: o dígito verificador de um CPF, ou o do
número de um processo. Uma linha que falha a conferência pode ser relida
por outra família de OCR (`confirm=`). O mesmo valor inválido nas duas
leituras mostra que o erro está impresso no documento; um valor válido no
mesmo lugar substitui a linha. Só o que continua sem explicação vai a um
leitor caro, com teto opcional de páginas e de tempo.

O caso principal são os autos judiciais. Qualquer campo com forma impressa e
regra de validade entra como verificação própria. Tudo roda na sua máquina,
salvo o leitor externo que você autorizar.

> **Alpha.** Nada publicado no PyPI ainda, e a API pode mudar.

## In English

<!-- --8<-- [start:english] -->
`docaudit` reads scanned and born-digital PDFs, and page images, in two tiers.
A cheap tier (the PDF text layer, then PP-OCR on CPU) reads every page.
Categorical checks that need no reference text (CPF, CNPJ and CNJ check
digits, impossible amount spelling, empty or garbled reads) flag where that
reading failed. A second OCR family re-reads those lines to tell a misprint
in the document from a misread. Only what remains goes to a stronger reader,
under an optional cap in pages and in seconds: a larger OCR, a local
vision-language model, or an OpenAI-compatible endpoint you explicitly allow.
Every chunk carries page, normalized bounding box, reader and confidence.
The documentation is in Brazilian Portuguese; identifiers and the API are in
English.
<!-- --8<-- [end:english] -->

## Instalação

```bash
uv add "docaudit[ppocr,openvino] @ git+https://github.com/hugohonda/docaudit"
```

Python 3.12 a 3.14, em Linux (x86_64 e aarch64) ou em macOS com Apple
Silicon. O extra `ppocr` traz o OCR padrão, e os pesos baixam na primeira
leitura. O extra `openvino` roda o mesmo PP-OCR mais depressa na CPU. Os
outros extras, o binário do Tesseract e a GPU estão em
[Instalação](https://hugohonda.github.io/docaudit/install/).

Uma tag `v*` publicada não muda, e a `main` não recebe push forçado: o
repositório recusa os dois. Fixe o commit ou a tag: o que você fixou continua lá.

## Uso

```python
import docaudit
from docaudit import Budget
from docaudit.backends.ppocr import PPOCR

result = docaudit.process(
    "autos.pdf",
    policy="evidence",  # encaminha só a página em que a leitura barata falhou numa verificação
    strong=PPOCR("v6-medium"),  # o leitor caro: aqui, um OCR maior
    budget=Budget(max_strong_fraction=0.1),  # teto opcional, em páginas
)

for chunk in result.chunks[:5]:
    print(chunk.page, chunk.source, chunk.bbox, chunk.text[:60])

for decision in result.decisions:
    if decision.tier == "strong":
        print(decision.page, decision.reason)  # por exemplo: 1 x CPF que falha a verificação

print(result.spent.pages_strong, "páginas foram ao leitor caro")
```

Só com o documento, `process` lê a camada de texto onde houver, manda o
resto ao PP-OCR e não encaminha nenhuma página ao leitor caro. Uma imagem
PNG, JPEG, TIFF, BMP ou WebP é lida como um PDF de uma página por quadro.

A primeira leitura, passo a passo, está no
[tutorial](https://hugohonda.github.io/docaudit/tutorial/).

## O que volta

Um `Result` com:

- `pages`: o substrato de cada página (nato-digital, digitalizada com camada
  de OCR, digitalizada sem texto) e as imagens que nenhuma camada de texto leu;
- `chunks`: o texto lido, um trecho por linha ou por região, cada um com
  página, caixa normalizada, leitor de origem, confiança e ordem de leitura;
- `decisions`: para cada página, o destino, o motivo e os passos que
  `process` deu nela;
- `entities`: cada CPF, CNPJ, número de processo, valor em reais e data
  achado nas linhas, com o estado que a regra deu (`confirmed`,
  `well_formed`, `failed`) e as linhas de onde saiu. Os campos do seu tipo de
  documento entram como `Check`;
- `spent`: o que a execução gastou, relatado e não limitado. São as páginas
  por etapa, as leituras servidas pelo cache, os segundos por etapa e, num
  leitor externo, os tokens e os dólares.

`result.to_markdown()` dá o texto por página. Com `annotated=True`, cada linha
ganha uma referência curta para ser citada, e cada página termina com a
decisão e as entidades. É a forma de entregar a leitura a um modelo: ver
[Entregar a leitura a um agente](https://hugohonda.github.io/docaudit/agent/).
`docaudit.visualize(result, "autos.pdf")` dá a imagem de cada página com a
caixa de cada linha na cor do leitor que a leu. Os campos estão em
[Formato da resposta](https://hugohonda.github.io/docaudit/response/).

## O que não faz

Não monta tabelas em células, não extrai campos por esquema e não decide
nada com um modelo de linguagem. A lista completa está em
[Limites](https://hugohonda.github.io/docaudit/limits/).

## Documentação

O site é <https://hugohonda.github.io/docaudit/>. Comece pela
[instalação](https://hugohonda.github.io/docaudit/install/) e pela
[primeira leitura](https://hugohonda.github.io/docaudit/tutorial/). Cada
argumento e cada variável de ambiente estão em
[Configuração](https://hugohonda.github.io/docaudit/configuration/).

## Contribuir

Ver [CONTRIBUTING.md](CONTRIBUTING.md). As convenções de código e de prosa
estão em [AGENTS.md](AGENTS.md) e valem para contribuições humanas e de
agentes. As mudanças de cada versão estão no [CHANGELOG](CHANGELOG.md).

## Licença

MPL-2.0 (Mozilla Public License 2.0). Quem altera um arquivo da biblioteca
publica a alteração sob a mesma licença. Quem só a usa, inclusive junto de
código fechado em outros arquivos, deve apenas o crédito.
