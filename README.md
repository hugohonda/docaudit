# docaudit

Documentação: <https://hugohonda.github.io/docaudit/>

Leitura de documentos digitalizados em português do Brasil, com conferência
da leitura e a origem de cada trecho.

`docaudit` lê todas as páginas com um leitor barato. Depois confere o que
leu com regras que o próprio documento traz: o dígito verificador de um CPF,
ou o do número de um processo. A página com uma linha que falha a
conferência pode ser relida por outra família de OCR (`confirm=`), que lê a
página inteira. A comparação é nas linhas que falharam. O mesmo valor
inválido nas duas leituras mostra que o erro está impresso no documento; um
valor válido no mesmo lugar substitui a linha. Só o que continua sem
explicação vai a um leitor caro, com teto opcional de páginas e de tempo.

O caso principal são os autos judiciais. Qualquer campo com forma impressa e
regra de validade entra como verificação própria. Tudo roda na sua máquina,
salvo o leitor externo que você autorizar.

> **Alpha.** Nada publicado no PyPI ainda, e a API pode mudar.

## In English

<!-- --8<-- [start:english] -->
`docaudit` reads scanned and born-digital PDFs, and page images, in two tiers.
A cheap tier (the PDF text layer, then PP-OCR on CPU) reads every page; on a
scan that carries an OCR layer, PP-OCR reads the pixels by default and the
layer stays as a second reading.
Categorical checks that need no reference text (CPF, CNPJ and CNJ check
digits, impossible amount spelling, empty or garbled reads) flag where that
reading failed. A second OCR family re-reads those pages and compares the
failing lines, to tell a misprint in the document from a misread. Only what
remains goes to a stronger reader, under an optional cap in pages and in
seconds: a larger OCR, a local vision-language model, or an OpenAI-compatible
endpoint you explicitly allow.
Every chunk carries page, normalized bounding box, reader and confidence.
The documentation is in Brazilian Portuguese; identifiers and the API are in
English.
<!-- --8<-- [end:english] -->

## Instalação

```bash
uv add "docaudit[ppocr,openvino] @ git+https://github.com/hugohonda/docaudit"
```

O extra `ppocr` traz o OCR padrão, e o extra `openvino` o roda mais depressa
na CPU. As plataformas, os outros extras e a GPU estão em
[Instalação](https://hugohonda.github.io/docaudit/install/). Como fixar um
commit ou uma tag está em
[Versões e mudanças](https://hugohonda.github.io/docaudit/changelog/).

## Uso

```python
import docaudit

result = docaudit.process("autos.pdf")

for chunk in result.chunks[:5]:
    print(chunk.page, chunk.source, chunk.bbox, chunk.text[:60])

for entity in result.entities:
    print(entity.page, entity.kind, entity.value, entity.state)
```

Só com o documento, `process` lê a camada de texto onde houver e manda o
resto ao PP-OCR. Nenhuma página vai ao leitor caro.

O resto está na documentação:

- [Primeira leitura](https://hugohonda.github.io/docaudit/tutorial/): o
  primeiro documento, passo a passo.
- [Escalar só o que falhou](https://hugohonda.github.io/docaudit/how-to/escalate/):
  o leitor caro, a releitura por outra família e o teto.
- [Formato da resposta](https://hugohonda.github.io/docaudit/response/): o
  que volta no `Result`.
- [Configuração](https://hugohonda.github.io/docaudit/configuration/): cada
  argumento e cada variável de ambiente.
- [Limites](https://hugohonda.github.io/docaudit/limits/): o que a
  biblioteca não faz.

## Contribuir

Ver [CONTRIBUTING.md](CONTRIBUTING.md). As convenções de código e de prosa
estão em [AGENTS.md](AGENTS.md) e valem para contribuições humanas e de
agentes. As mudanças de cada versão estão no [CHANGELOG](CHANGELOG.md).

## Licença

MPL-2.0 (Mozilla Public License 2.0). Quem altera um arquivo da biblioteca
publica a alteração sob a mesma licença. Quem só a usa, inclusive junto de
código fechado em outros arquivos, deve apenas o crédito.
