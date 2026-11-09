# API

A API pública é o que `docaudit` exporta em `__all__`. Um nome fora dessa
lista é privado e pode mudar sem aviso, mesmo sem sublinhado. Os módulos
`docaudit.policies` e `docaudit.backends.*` têm a sua própria lista, e a
página de cada um a documenta.

Cada nome abaixo leva à página em que está documentado. A referência sai das
docstrings do código.

| nome | o que é | página |
|---|---|---|
| [`process`][docaudit.process.process] | lê um documento e devolve o `Result` | [Ponto de entrada](entry.md) |
| [`Document`][docaudit.session.Document] | o documento aberto, para ler e reler por partes | [Ponto de entrada](entry.md) |
| [`Doubt`][docaudit.session.Doubt] | a linha que `Document.doubts()` aponta para revisão | [Ponto de entrada](entry.md) |
| [`visualize`][docaudit.visualize.visualize] | cada página como imagem, com a caixa de cada trecho na cor do leitor | [Ponto de entrada](entry.md) |
| [`mark_furniture`][docaudit.process.mark_furniture] | marca os elementos fixos das linhas de várias páginas | [Ponto de entrada](entry.md) |
| [`Result`][docaudit.types.Result] | o resultado de uma leitura | [Resultado](types.md) |
| [`Page`][docaudit.types.Page] | uma página classificada | [Resultado](types.md) |
| [`PageDimensions`][docaudit.types.PageDimensions] | largura e altura em pontos e em pixels, e o DPI | [Resultado](types.md) |
| [`Substrate`][docaudit.types.Substrate] | de onde veio a camada de texto da página | [Resultado](types.md) |
| [`Stamp`][docaudit.types.Stamp] | a tarja do sistema eletrônico do tribunal | [Resultado](types.md) |
| [`Folha`][docaudit.types.Folha] | o número da folha dos autos, carimbado na página | [Resultado](types.md) |
| [`Chunk`][docaudit.types.Chunk] | um trecho lido, com página, caixa e leitor | [Resultado](types.md) |
| [`BBox`][docaudit.types.BBox] | a caixa normalizada a `[0, 1]` | [Resultado](types.md) |
| [`Region`][docaudit.types.Region] | uma região de layout: rótulo e caixa | [Resultado](types.md) |
| [`Entity`][docaudit.types.Entity] | um valor achado por uma verificação, com estado | [Resultado](types.md) |
| [`EntityState`][docaudit.types.EntityState] | `confirmed`, `well_formed` ou `failed` | [Resultado](types.md) |
| [`OtherReading`][docaudit.types.OtherReading] | outra leitura do mesmo lugar da página | [Resultado](types.md) |
| [`Figure`][docaudit.types.Figure] | uma imagem de página nato-digital e as linhas lidas nela | [Resultado](types.md) |
| [`Record`][docaudit.types.Record] | um bloco de linhas vizinhas | [Resultado](types.md) |
| [`Piece`][docaudit.types.Piece] | páginas seguidas com a mesma tarja | [Resultado](types.md) |
| [`RoutingDecision`][docaudit.types.RoutingDecision] | o destino e o motivo de cada página | [Resultado](types.md) |
| [`Tier`][docaudit.types.Tier] | `cheap` ou `strong` | [Resultado](types.md) |
| [`Budget`][docaudit.types.Budget] | o teto do leitor caro, em páginas e em segundos | [Resultado](types.md) |
| [`Spent`][docaudit.types.Spent] | o que a leitura gastou | [Resultado](types.md) |
| [`Run`][docaudit.types.Run] | os leitores, as versões e os argumentos da leitura | [Resultado](types.md) |
| [`DocumentFacts`][docaudit.types.DocumentFacts] | o que o arquivo PDF diz de si | [Resultado](types.md) |
| [`Signature`][docaudit.types.Signature] | uma assinatura digital declarada no PDF | [Resultado](types.md) |
| [`Reread`][docaudit.types.Reread] | `"page"` ou `"region"` | [Resultado](types.md) |
| [`TrustLayer`][docaudit.types.TrustLayer] | `"visible"` ou `"always"` | [Resultado](types.md) |
| [`DocumentError`][docaudit.types.DocumentError] | o documento não abre | [Resultado](types.md) |
| [`ExternalBackendError`][docaudit.types.ExternalBackendError] | um leitor externo foi pedido sem autorização | [Resultado](types.md) |
| [`TriagePolicy`][docaudit.types.TriagePolicy] | o contrato de uma política | [Políticas e verificações](policies.md) |
| [`Reader`][docaudit.types.Reader] | o contrato de um leitor | [Leitores](readers.md) |
| [`Metered`][docaudit.types.Metered] | o leitor que conta chamadas, tokens e dólares | [Leitores](readers.md) |
| [`Layout`][docaudit.types.Layout] | o contrato de um detector de layout | [Leitores](readers.md) |
| [`PageView`][docaudit.pdf.PageView] | a vista de uma página que um leitor recebe | [Leitores](readers.md) |
| [`get_backend`][docaudit.registry.get_backend] | resolve um leitor pelo nome registrado | [Leitores](readers.md) |
| [`doc_id_for`][docaudit.pdf.doc_id_for] | o identificador de um documento, do SHA-256 dos bytes | [PDF e cache](pdf-cache.md) |
| [`ModelCallCache`][docaudit.cache.ModelCallCache] | o cache das leituras, em SQLite | [PDF e cache](pdf-cache.md) |
| `__version__` | a versão instalada do pacote, como texto | esta página |

```pycon
>>> import docaudit
>>> docaudit.__version__  # a versão instalada; varia
'0.1.0.dev1'
```
