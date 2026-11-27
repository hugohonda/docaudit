# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/1.1.0/).
Versionamento: [SemVer](https://semver.org/lang/pt-BR/): o maior sobe quando
algo público quebra, o menor quando algo entra, o último numa correção.
Antes da 1.0.0, a API pode mudar numa versão menor.

<!-- --8<-- [start:versoes] -->
## [Não lançado]

## [0.1.0.dev4] - 2026-11-27

### Adicionado

- `Page.unread_lines` traz a caixa de cada linha que o PP-OCR detectou e não leu. A página em
  que elas são mais que as linhas lidas aparece em `Result.review()` com o motivo novo
  `unread_lines`. A folha manuscrita, a cópia fraca e a digitalização que o reconhecedor não
  soube ler voltavam com poucas linhas ou nenhuma, sem marca. `RoutingDecision.incomplete` não
  muda de sentido: segue dizendo que um leitor falhou.
- O sinal `UnreadLines` entra em `DEFAULT_SIGNALS`: a política `evidence` encaminha ao leitor
  caro a página com mais linhas detectadas do que lidas. Com `EvidenceRouter([EmptyRead(),
  UnreadLines()])` e um teto em `Budget`, só a página que a leitura barata não leu vai a um
  leitor externo.
- `Chunk.as_read()` dá a caixa como a linha é lida, em pé. Quem agrupa ou ordena as linhas por
  conta própria precisa dela na página lida girada: `bbox` segue no sistema da imagem, e as
  linhas de uma folha de cabeça para baixo estão nele de baixo para cima.
- `AzureRead`, de `docaudit.backends.azure`, lê uma página pelo modelo de leitura do Azure AI
  Document Intelligence, só com a biblioteca padrão. É um leitor externo: `process()` exige
  `allow_external=True`. Devolve uma linha por trecho, com a caixa no sistema da imagem, o giro
  de cada linha e a confiança da palavra mais duvidosa dela. Conta as páginas enviadas e, com
  `price_per_page`, os dólares. A chave recusada interrompe o documento; as outras falhas do
  serviço são da página, que fica com a leitura barata. Com `on_result`, entrega o
  `analyzeResult` de cada página inteira a quem o guarda, e `lines_of` monta as linhas de um
  resultado guardado sem chamar o serviço.
- `Read`, de `docaudit.types`, é o que um leitor devolve quando sabe o que deixou sem ler: a
  lista das linhas, com as caixas sem leitura em `unread`. Uma lista comum continua valendo.

- `Chunk.inked`: se a linha da camada de texto está desenhada com tinta, sem imagem por cima.

- `Result.evidence(entity)` lista os fatos do resultado que sustentam ou contradizem uma
  ocorrência: a regra do campo, o texto composto, as outras leituras do mesmo lugar, o mesmo valor
  por outra fonte na mesma página e em outras páginas, e um valor vizinho a poucos caracteres. Cada
  fato é um `Evidence`, com a fonte e as linhas. É uma lista, e não um veredito.

- `Entity.id` é a identidade de cada ocorrência de um valor, estável entre leituras que dão as
  mesmas linhas, e a propriedade `Entity.key` é o valor só com letras e dígitos.
  `Result.occurrences(entity)` devolve as outras ocorrências do mesmo valor: o número do processo
  na tarja de cada página e no corpo, por exemplo.

- `Check.valid_only`: uma forma fora da pontuação padrão que conta só quando a regra confere. O
  `CPF` a usa para o ponto ou a barra lidos no lugar do hífen, `529.982.247.25`: se os dígitos
  fecham, é o CPF; se não fecham, é outro número e não sai. Como a forma com rótulo, entra em
  `Result.entities` e não encaminha a página.

- `Result.review()` diz, por página, os motivos para uma pessoa olhar: um leitor que falhou, um
  valor que falha a regra, o erro que outra família repete e a linha lida de dois modos. São fatos
  do resultado, sem limiar. `Result.readings(entity)` dá as outras leituras das linhas de um valor.
  Quem usava a biblioteca refazia essas duas junções por fora.
- `Result.schema_version` diz a versão do formato do JSON, e o esquema da versão corrente está em
  `docs/response/result.schema.json`. A versão sobe quando um campo sai, muda de tipo ou muda de
  sentido; um campo novo com padrão não a muda. Um JSON gravado antes de o campo existir é lido
  como da versão 1.

- `form_of` e `within`, de `docaudit.process`, `page_bounds`, de `docaudit.pdf`, e `turned`, de
  `docaudit.backends.ppocr`, são nomes públicos. São regras da cascata que uma medição precisa
  repetir sem copiar: a forma que iguala duas linhas de elemento fixo, o que conta como lido numa
  região, a caixa de um objeto do PDF em coordenadas da página e o recorte que o reconhecedor girou.

- `Page.gazette` traz o cabeçalho de diário oficial da página: a edição, a data, o ano, o caderno
  e a página da edição. Três formatos (`GazetteFormat`) vêm por omissão: o Diário da Justiça
  Eletrônico de São Paulo e duas formas de diário municipal; `process(gazettes=)` troca ou desliga.
  Páginas da mesma edição trazem a mesma `edition`, o que dá a unidade de publicação de um diário.

### Mudado

- O PP-OCR lê em pé a página digitalizada de cabeça para baixo. Ele reconhece de novo, em
  meia-volta, as linhas deitadas mais largas; se a maioria lê melhor assim, lê a página girada e
  compara as duas leituras linha a linha. `Chunk.turn` aceita `180`, e o giro é da linha: o
  rodapé carimbado em pé sobre a folha invertida segue com `0`, e a tarja vertical da margem
  leva o giro da folha. A linha curta, que lê quase igual nos dois sentidos, segue o giro da
  folha. A página em pé bem lida não paga a sonda. O `output_version` do `ppocr` sobe, e o cache dele é relido.
- `SCHEMA_VERSION` passa a `"2"`: `turn` ganha o valor `180`. `Page.unread_lines` é campo novo
  com padrão. Um JSON gravado sem `schema_version` continua lido como da versão 1.
- A releitura por outra família (`confirm=`) mostra ao leitor de pixels a página com o giro
  da leitura barata. O Tesseract lia como lixo a página que a barata tinha lido de lado ou de
  cabeça para baixo, e nunca confirmava um valor nela.
- `Result.records()` agrupa as linhas de cabeça para baixo em fileiras e blocos, na ordem em
  que são lidas, e nunca na mesma fileira de uma linha em pé.
- A política `evidence` encaminha mais páginas: as do sinal `UnreadLines`. Quem passa a
  própria lista de sinais não muda.

- Numa digitalização com camada de OCR, a linha desenhada à vista por cima da imagem é texto
  composto (`Page.composes`): a tarja e a folha do tribunal dão `composed_text`, e o valor delas
  que falha sai com `printed="text_layer"`. A camada oculta segue como leitura de um motor. O
  `output_version` de `text_layer` sobe, e o cache dele é relido.

- O teto de páginas de `Budget` é aplicado depois da releitura por outra família. A releitura roda
  em toda página que uma verificação encaminhou, e a página que ela explica não gasta o teto. Com
  um teto curto, `Entity.printed` passa a cobrir toda página encaminhada, e o leitor caro recebe
  as primeiras páginas que ficaram sem explicação. A releitura lê mais páginas do que lia com teto.

- A documentação de `reread="region"` diz a quem o recorte serve: ao leitor que cobra pela área
  da imagem. Com um OCR de pixels em `strong=`, a releitura da página inteira traz mais valores,
  e o exemplo do guia passa a usar um modelo de visão e linguagem.

### Removido

- `RENAVAM` sai de `docaudit.policies` e de `IDENTIFIERS`. Onze dígitos depois do rótulo casavam
  outros números em documentos reais, e o dígito verificador único não bastava para separar o
  falso positivo. Quem o usava declara a própria `Check`, como em `docs/how-to/checks.md`.

### Corrigido

- A linha barata sai quando está no mesmo lugar de uma linha do leitor caro, nos dois sentidos:
  o centro dela numa caixa cara, ou o centro de uma linha cara na caixa dela. Com um leitor caro
  que devolve linhas, e não blocos, a linha barata que atravessava duas colunas tinha o centro no
  vão entre elas e ficava no resultado, ao lado da leitura que a substituía.

- Com `reread="region"`, o pedaço da linha vizinha que o leitor caro devolve junto com a linha
  relida não entra mais no resultado. O recorte de uma linha leva a borda das vizinhas; fica só
  o que cruza a altura do meio da linha pedida.

- O valor em reais sem `R$` e com ponto decimal, `4.329.30`, não casa mais o número logo depois de
  `nº` nem o seguido de hífen ou barra e dígito: `Proc. nº 533.505.49-00` é um número de processo,
  e saía como valor que falha a regra.

## [0.1.0.dev3] - 2026-11-13

### Corrigido

- A página e a cópia dela não provam o elemento fixo uma da outra. Duas páginas com o mesmo
  conjunto de formas nas linhas horizontais com letra são cópia; a linha vertical da margem fica
  fora da comparação. A peça juntada duas vezes marcava a página inteira, corpo e valores
  inclusive. Quando todas as páginas lidas são cópia umas das outras, a regra não vale.
- Leituras erradas que saíam `confirmed` ou corrigidas:
  - `DATE_WEEKDAY` não tem redundância: o dia da semana se repete a cada sete dias, e a data que
    confere sai `well_formed`.
  - O CNPJ com letra que confere sai `well_formed`; só o numérico sai `confirmed`.
  - O valor por extenso sem número entre parênteses sai `well_formed`.
  - A releitura de outra família só conserta um valor sem prova quando mantém, na mesma
    posição, cada dígito que a leitura barata leu.
  - A linha do leitor caro recusada por perder um valor vai a `Result.others`, com o campo e o
    valor, e aparece em `Document.doubts()`.
- Leituras certas que falhavam, e texto que sumia:
  - `pagou Cr$ 1.000.` não falha: o ponto final da frase não é parte do número.
  - O espaço entre grupos do valor em reais só falha logo depois do `R$`: duas células vizinhas,
    `3` e `150,00`, não falham.
  - A linha da camada escrita em diagonal, como a marca d'água de uma cópia, não esconde as
    linhas do raster embaixo dela.
  - O cache guarda se o leitor pediu os pixels, e não se a vista já estava renderizada.
  - Com `layout=`, a página lida de lado sai, dentro de cada bloco, de cima para baixo.
  - Uma letra só não é tarja vertical.
  - Duas sequências de folha empatadas deixam todas as folhas fora da sequência.

### Alterado

- A regra do número sem `R$` segue a verificação marcada com `Check.bare`, e não a identidade de
  `AMOUNT_BRL`. Quem passa `entities=` sem uma verificação `bare` fica sem ela.
- A camada oculta escrita pelo Tesseract não confirma o que o Tesseract leu: não é outra família.
- A documentação diz o que o código faz: a receita de tarja redige pela posição do valor, o teto
  do leitor caro, a página que o leitor caro recusa com `all_strong`, a camada de OCR que não é a
  leitura por padrão, e o carimbo e a folha que seguem `stamps=` e `folhas=`.

### Adicionado

- `Check.unproven`, `Check.proves` e `Check.bare`; `TesseractOCR.layer_font`;
  `DrawnLine.slanted`, `PageView.drawn_lines()` e `PageView.requests`.

## [0.1.0.dev2] - 2026-11-08

### Corrigido

- A linha da camada de texto cuja palavra hifenizada continua noutra coluna, ou depois de
  outra linha, sai em duas linhas, cada uma com a caixa dela. A junção do pdfium fazia uma
  caixa que atravessava a coluna. Muda o id desses trechos.
- Em `Result.records()`, a linha que cobre duas linhas que não se tocam, como uma célula mesclada
  ou uma tarja vertical, fica numa fileira sozinha. Ela juntava a tabela inteira numa fileira.
- O pacote volta a construir num commit depois de uma tag `.devN`: a versão é a da tag mais o
  commit (`0.1.0.dev1+g<commit>`).

### Alterado

- A documentação passa a ter tutorial, guias, explicação e referência separados, um glossário,
  instalação por plataforma, problemas comuns e a página de versões. `Record` e `Piece` são
  exportados por `docaudit`.

## [0.1.0.dev1] - 2026-11-08

### Adicionado

- `MojibakeText`, o sinal da camada de texto decodificada com a codificação errada, no extra
  `mojibake` (ftfy). Fora de `DEFAULT_SIGNALS`.
- `RoutingDecision.seconds`: os segundos de cada etapa em cada página.
- `PPOCR` e `PPDocLayout` com `threads=None` seguem os núcleos disponíveis ao processo quando
  são menos que os da máquina (`cpuset` de contêiner).
- `Result.records()`: as linhas de cada página em fileiras e blocos, só pela posição das
  caixas, com `Record.text` e `Record.tabular`. `Result.pieces()`: as páginas seguidas com a
  mesma tarja, por `Stamp.code`.
- `Budget.max_seconds`: o teto de tempo a partir do qual o leitor caro não começa página nova.
- `process(min_raster_fraction=)`: o piso de área abaixo do qual um raster de uma página
  nato-digital não vai ao leitor de pixels. Padrão `0.0`, o comportamento de antes; o valor não
  está calibrado.
- `PPOCR(det=)`: um detector ONNX próprio, com o hash no nome e na versão de saída.
- `VLM(retries=)`: repete a chamada que o servidor recusou por carga, que esgotou o tempo ou
  cuja conexão caiu. Num servidor fora da máquina, a recusa esgotada é falha da página, e o
  documento segue.
- `StampFormat.tz`: o fuso do tribunal, que torna `Stamp.at` ciente do fuso. Sem ele, a hora
  fica como impressa.
- Um leitor `vlm` com o mesmo detector de `process(layout=)` reaproveita os blocos já detectados
  da página, em vez de detectar de novo.

### Alterado

- A licença passa de Apache-2.0 para MPL-2.0. Cada arquivo fonte traz o aviso do Anexo A.
- O leitor caro não prova mais erro do documento: `Entity.printed` sai só da camada de
  texto ou da releitura por outra família (#7).
- `docaudit` exporta `Run`, `Region` e `Layout`, que já eram parte de `Result` e de
  `process(layout=)`.
- O classificador do pacote passa de Pre-Alpha para Alpha, como o README diz.

### Corrigido

- `pixels_of` destrói o bitmap do pdfium sob o lock e devolve, em cinza, uma cópia que não
  aponta para o buffer dele.
- Em ARM64, o OpenCV fica abaixo de 4.14: o `resize` das versões 4.14 e 5.0 lê além da
  imagem e derruba o processo (#8).
- O workflow de documentação instala o pacote, que o mkdocstrings importa, e o de
  publicação só segue a partir de uma tag `v*`.

## [0.1.0.dev0] - 2026-11-05

A primeira versão, em desenvolvimento. O pacote lê documentos digitalizados em português do
Brasil, confere a leitura com regras que o documento permite checar e devolve cada trecho
com a página, a caixa e o leitor de origem.

- Leitores: camada de texto, Tesseract, PP-OCR (ONNX Runtime ou OpenVINO) e um servidor
  compatível com a API da OpenAI (`vlm`); detector de layout `PPDocLayout`.
- Políticas `all_cheap`, `all_strong` e `evidence`; releitura por outra família com
  `confirm=`; teto de páginas em `Budget`.
- Doze entidades padrão com estado `confirmed`, `well_formed` ou `failed`, e `Check` para
  campos próprios.
- `Result.to_markdown(annotated=True)` e `Result.cited` para um agente; `Document` e
  `Doubt` para uma sessão; `visualize` para a imagem com as caixas.
- Cache de leituras em SQLite; nada sai da máquina sem `allow_external=True`.

[Não lançado]: https://github.com/hugohonda/docaudit/compare/v0.1.0.dev4...HEAD
[0.1.0.dev4]: https://github.com/hugohonda/docaudit/compare/v0.1.0.dev3...v0.1.0.dev4
[0.1.0.dev3]: https://github.com/hugohonda/docaudit/compare/v0.1.0.dev2...v0.1.0.dev3
[0.1.0.dev2]: https://github.com/hugohonda/docaudit/compare/v0.1.0.dev1...v0.1.0.dev2
[0.1.0.dev1]: https://github.com/hugohonda/docaudit/compare/v0.1.0.dev0...v0.1.0.dev1
[0.1.0.dev0]: https://github.com/hugohonda/docaudit/releases/tag/v0.1.0.dev0
<!-- --8<-- [end:versoes] -->
