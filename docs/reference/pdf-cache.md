# PDF e cache

`docaudit.pdf` abre o documento, classifica o substrato de cada página e
renderiza. `docaudit.cache` guarda cada leitura num arquivo SQLite. A vista da
página que um leitor recebe, `PageView`, está em [Leitores](readers.md#a-vista-da-pagina).
Todo acesso ao pdfium passa por um lock do módulo: a biblioteca não é segura
para uso concorrente.

## Abrir e classificar

::: docaudit.pdf.doc_id_for
    options:
      heading_level: 3

::: docaudit.pdf.opened
    options:
      heading_level: 3

::: docaudit.pdf.pages_of
    options:
      heading_level: 3

::: docaudit.pdf.load_pages
    options:
      heading_level: 3

::: docaudit.pdf.facts_of
    options:
      heading_level: 3

::: docaudit.pdf.load_facts
    options:
      heading_level: 3

::: docaudit.pdf.is_image
    options:
      heading_level: 3

::: docaudit.pdf.pdf_of_image
    options:
      heading_level: 3

## Renderizar

::: docaudit.pdf.pixels_of
    options:
      heading_level: 3

::: docaudit.pdf.render_of
    options:
      heading_level: 3

::: docaudit.pdf.DEFAULT_DPI
    options:
      heading_level: 3

::: docaudit.pdf.MIN_NATIVE_DPI
    options:
      heading_level: 3

::: docaudit.pdf.MAX_NATIVE_DPI
    options:
      heading_level: 3

## Camada de texto

::: docaudit.pdf.text_lines_of
    options:
      heading_level: 3

::: docaudit.pdf.drawn_lines_of
    options:
      heading_level: 3

::: docaudit.pdf.TextLine
    options:
      heading_level: 3

::: docaudit.pdf.DrawnLine
    options:
      heading_level: 3

## Cache

::: docaudit.cache.ModelCallCache
    options:
      heading_level: 3

::: docaudit.cache.call_key
    options:
      heading_level: 3

::: docaudit.cache.default_cache_path
    options:
      heading_level: 3
