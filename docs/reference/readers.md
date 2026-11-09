# Leitores

Um leitor recebe a vista de uma página (`PageView`) e devolve trechos
(`Chunk`). O mesmo contrato serve à cascata barata (`cheap=`), à releitura por
outra família (`confirm=`) e ao leitor caro (`strong=`). Os parâmetros de
cada leitor, em tabela, estão em [Configuração](../configuration.md#leitores).
Como escrever um leitor novo está em [Escrever um leitor](../writing-a-reader.md).

## Contratos

::: docaudit.types.Reader
    options:
      heading_level: 3

::: docaudit.types.Metered
    options:
      heading_level: 3

::: docaudit.types.Layout
    options:
      heading_level: 3

## A vista da página

::: docaudit.pdf.PageView
    options:
      heading_level: 3

::: docaudit.pdf.RegionView
    options:
      heading_level: 3

## Nomes registrados

`cheap=`, `strong=` e `confirm=` aceitam o nome de um leitor no lugar da
instância. O nome vem do grupo de entry points `docaudit.backends`, e
`get_backend` o resolve.

::: docaudit.registry.get_backend
    options:
      heading_level: 3

::: docaudit.backends.textlayer.TextLayerReader

::: docaudit.backends.tesseract.TesseractOCR

::: docaudit.backends.ppocr.PPOCR

::: docaudit.backends.vlm.VLM

::: docaudit.backends.vlm.DEFAULT_URL
    options:
      heading_level: 3

::: docaudit.backends.vlm.PRESETS
    options:
      heading_level: 3

::: docaudit.backends.layout.PPDocLayout

::: docaudit.backends.layout.DROP_DEFAULT
    options:
      heading_level: 3

::: docaudit.backends.layout.LABELS
    options:
      heading_level: 3
