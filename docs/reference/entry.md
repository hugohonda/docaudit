# Ponto de entrada

As quatro formas de chamar a biblioteca. `process()` lê um documento de uma
vez. `Document` guarda o documento aberto para ler e reler por partes, e
`Doubt` é a linha que ele aponta para revisão. `visualize()` desenha as caixas
do resultado sobre as páginas. A tabela dos argumentos de `process()` está em
[Configuração](../configuration.md#process).

::: docaudit.process.process

::: docaudit.session.Document

::: docaudit.session.Doubt

::: docaudit.visualize.visualize

## Outros nomes de `docaudit.process`

`mark_furniture` é a regra que marca os elementos fixos, exposta para quem
monta as linhas por conta própria. `stamps_of` e `folhas_of` acham a tarja e o
carimbo de folha de cada página. As duas constantes são a cascata padrão e a
folga em volta do recorte de um raster. `resolve`, `refuse_external`,
`read_region` e `run_pipeline` são os passos de `process()` que `Document`
também usa, sobre um documento já aberto. `form_of` e `within` são duas regras
pequenas da cascata, expostas para quem mede o que ela faz: a forma que iguala
duas linhas de elemento fixo, e o que conta como lido dentro de uma região.

::: docaudit.process.mark_furniture
    options:
      heading_level: 3

::: docaudit.process.stamps_of
    options:
      heading_level: 3

::: docaudit.process.folhas_of
    options:
      heading_level: 3

::: docaudit.process.form_of
    options:
      heading_level: 3

::: docaudit.process.within
    options:
      heading_level: 3

::: docaudit.process.DEFAULT_CASCADE
    options:
      heading_level: 3

::: docaudit.process.RASTER_MARGIN
    options:
      heading_level: 3

::: docaudit.process.resolve
    options:
      heading_level: 3

::: docaudit.process.refuse_external
    options:
      heading_level: 3

::: docaudit.process.read_region
    options:
      heading_level: 3

::: docaudit.process.run_pipeline
    options:
      heading_level: 3
