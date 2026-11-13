# Resultado

Os tipos de `docaudit.types`: o `Result` que `process()` devolve e cada peça
dele. As classes de dados são modelos Pydantic congelados. A página traz
também enumerações, aliases de tipo, constantes e funções. O que cada campo traz, em prosa e
com exemplo, está em [Campos do resultado](../response/fields.md).

Os contratos de extensão do mesmo módulo ficam nas páginas de quem os usa:
`Reader`, `Layout` e `Metered` em [Leitores](readers.md), `TriagePolicy` em
[Políticas e verificações](policies.md).

## Resultado

::: docaudit.types.Result
    options:
      heading_level: 3

## Página

::: docaudit.types.Page
    options:
      heading_level: 3

::: docaudit.types.PageDimensions
    options:
      heading_level: 3

::: docaudit.types.Substrate
    options:
      heading_level: 3

::: docaudit.types.Stamp
    options:
      heading_level: 3

::: docaudit.types.Folha
    options:
      heading_level: 3

## Trecho e caixa

::: docaudit.types.Chunk
    options:
      heading_level: 3

::: docaudit.types.BBox
    options:
      heading_level: 3

::: docaudit.types.Region
    options:
      heading_level: 3

::: docaudit.types.reading_order_key
    options:
      heading_level: 3

## Entidades e outras leituras

::: docaudit.types.Entity
    options:
      heading_level: 3

::: docaudit.types.EntityState
    options:
      heading_level: 3

::: docaudit.types.OtherReading
    options:
      heading_level: 3

## Figuras, blocos e peças

Saem de métodos de `Result`, e não de campos: `figures()`, `records()` e
`pieces()`.

::: docaudit.types.Figure
    options:
      heading_level: 3

::: docaudit.types.Record
    options:
      heading_level: 3

::: docaudit.types.Piece
    options:
      heading_level: 3

## Decisão, teto e gasto

::: docaudit.types.RoutingDecision
    options:
      heading_level: 3

::: docaudit.types.Tier
    options:
      heading_level: 3

::: docaudit.types.Budget
    options:
      heading_level: 3

::: docaudit.types.Spent
    options:
      heading_level: 3

::: docaudit.types.Run
    options:
      heading_level: 3

## O que o arquivo diz de si

::: docaudit.types.DocumentFacts
    options:
      heading_level: 3

::: docaudit.types.Signature
    options:
      heading_level: 3

::: docaudit.types.FormKind
    options:
      heading_level: 3

## Argumentos com valor fixo

::: docaudit.types.Reread
    options:
      heading_level: 3

::: docaudit.types.TrustLayer
    options:
      heading_level: 3

## Erros

::: docaudit.types.DocumentError
    options:
      heading_level: 3

::: docaudit.types.ExternalBackendError
    options:
      heading_level: 3

## Identificadores e cache

::: docaudit.types.ID_HEX_CHARS
    options:
      heading_level: 3

::: docaudit.types.DOC_ID_HEX_CHARS
    options:
      heading_level: 3

::: docaudit.types.SCHEMA_HEX_CHARS
    options:
      heading_level: 3

::: docaudit.types.chunk_schema_digest
    options:
      heading_level: 3
