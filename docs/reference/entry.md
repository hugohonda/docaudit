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
folga em volta do recorte de um raster.

::: docaudit.process.mark_furniture
    options:
      heading_level: 3

::: docaudit.process.stamps_of
    options:
      heading_level: 3

::: docaudit.process.folhas_of
    options:
      heading_level: 3

::: docaudit.process.DEFAULT_CASCADE
    options:
      heading_level: 3

::: docaudit.process.RASTER_MARGIN
    options:
      heading_level: 3
