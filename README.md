# docaudit

<!-- --8<-- [start:pitch] -->
Leitura de documentos digitalizados em português do Brasil, com verificação
da leitura e a origem de cada trecho.

`docaudit` lê todas as páginas com um leitor barato e confere a leitura com
regras que o próprio documento permite checar, como o dígito verificador de um
CPF ou de um número de processo. Uma linha que falha a conferência é relida
por outra família de OCR (`confirm=`): o mesmo valor inválido nas duas mostra
que o erro está impresso no documento, e um valor válido no mesmo lugar troca
a linha. Só o que continua sem explicação vai a um leitor mais caro, com um
teto opcional de páginas. O caso principal são os autos judiciais, mas
qualquer campo com forma impressa e regra de validade entra como verificação
própria, e tudo roda na sua máquina.

> **Alpha.** Nada publicado no PyPI ainda, e a API pode mudar.

> **In English.** `docaudit` reads scanned and born-digital PDFs, and page images, in two tiers.
> A cheap tier (the PDF text layer, then PP-OCR on CPU) reads every page.
> Categorical checks that need no reference text (CPF/CNPJ/CNJ check digits,
> impossible amount spelling, empty or garbled reads) flag where that reading
> failed. A second OCR family re-reads those lines to tell a misprint in the
> document from a misread. Only what remains goes, under an optional page cap,
> to a stronger reader: a larger OCR, a local vision-language model, or an
> OpenAI-compatible endpoint you explicitly allow. Every chunk carries page, normalized bounding
> box, reader and confidence. Documentation is in Brazilian Portuguese;
> identifiers and the API are in English.
<!-- --8<-- [end:pitch] -->

## Instalação

```bash
uv add "docaudit[ppocr,openvino] @ git+https://github.com/hugohonda/docaudit"
```

Python 3.12 a 3.14, em Linux ou macOS. O extra `ppocr` traz o OCR padrão, e os
pesos baixam na primeira leitura. Com o extra `openvino`, o PP-OCR roda mais depressa na
CPU. O extra `tesseract` pede também o binário
do Tesseract. O extra `layout` traz o detector de layout. Ver
[Começando](docs/getting-started.md).

## Uso

<!-- --8<-- [start:uso] -->
```python
import docaudit
from docaudit import Budget
from docaudit.backends.ppocr import PPOCR

result = docaudit.process(
    "autos.pdf",
    policy="evidence",  # escala só onde a leitura barata falhou numa verificação
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

Sem argumentos além do documento, `process` lê a camada de texto onde houver,
manda o resto ao PP-OCR e não escala nada. Uma imagem PNG, JPEG, TIFF, BMP ou WebP é
lida como um PDF de uma página por quadro.
<!-- --8<-- [end:uso] -->

## O que volta

Um `Result` com:

- `pages`: o tipo de cada página (nato-digital, digitalizada com OCR,
  digitalizada sem OCR) e as regiões que nenhuma camada de texto leu;
- `chunks`: o texto lido, um trecho por linha ou por região, cada um com
  página, caixa normalizada, leitor de origem, confiança e ordem de leitura;
- `decisions`: para cada página, o destino, o motivo e os passos que
  `process` deu nela;
- `entities`: cada CPF, CNPJ, número de processo, valor em reais e data
  achado nas linhas, com o estado que a regra deu (`confirmed`,
  `well_formed`, `failed`) e as linhas de onde saiu; campos do seu tipo de
  documento entram como `Check`;
- `spent`: o que foi gasto, relatado e não limitado: páginas por nível,
  leituras servidas pelo cache, segundos por etapa e, para um modelo
  hospedado, tokens e dólares.

`result.to_markdown()` dá o texto por página; com `annotated=True`
cada linha ganha uma referência curta para ser citada e cada página termina
com a decisão e as entidades, que é a forma de entregar a leitura a um
modelo ([Análise por um agente](docs/agent.md)).
`docaudit.visualize(result, "autos.pdf")` dá a imagem de cada folha com a
caixa de cada linha na cor do leitor que a leu. Ver
[Formato da resposta](docs/response.md).

## O que não faz

Não monta tabelas em células, não extrai campos por esquema e não decide
nada com um modelo de linguagem. A lista completa está em
[Limites](docs/limits.md).

## Documentação

Comece por [Começando](docs/getting-started.md). O índice das páginas está na
[visão geral](docs/index.md); argumentos e variáveis de ambiente estão em
[Configuração](docs/configuration.md).

## Contribuindo

Ver [CONTRIBUTING.md](CONTRIBUTING.md). As convenções de código e de prosa estão
em [AGENTS.md](AGENTS.md) e valem para contribuições humanas e de agentes. As
mudanças estão no [CHANGELOG](CHANGELOG.md).

## Licença

Apache-2.0.
