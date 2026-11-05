# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/1.1.0/).
Versionamento: [SemVer](https://semver.org/lang/pt-BR/): o maior sobe quando
algo público quebra, o menor quando algo entra, o último numa correção.
Antes da 1.0.0, a API pode mudar numa versão menor.

## [Não lançado]

### Adicionado

- `Entity.inferred` e `Check.inferred`: num valor em reais que falha, com milhar e dois
  dígitos depois do último ponto, a vírgula deduzida sai ao lado do valor literal. O texto
  lido, o estado e a escalada não mudam.

### Corrigido

- A linha do leitor caro com vírgula decimal e os mesmos dígitos do valor que falhou entra
  no lugar da barata, mesmo sem `R$` na linha.

### Removido

- O repositório fica só com o pacote, os testes dele e a documentação. O harness de
  medição, as notas e as ferramentas de revisão saem daqui.

### Licença

- O texto da licença Apache-2.0 fica em `LICENSE`, na raiz.

### Quebra

- `Page.document` sai: o código do documento está em `Page.stamp.code`;
- `document_codes` sai; `stamps_of` lê a tarja inteira;
- `ReadError` sai: o leitor que falha em todas as páginas não levanta
  exceção; a falha fica em `RoutingDecision.incomplete`, e o resultado
  volta com o que foi lido.

### Adicionado

- `Result.cited(..., entity=)`: a citação confere só se o valor da entidade
  está dentro dela; a citação resumida com reticências confere por pedaços,
  cada um inteiro e na ordem citada;
- `to_markdown(annotated=True)` lista, por página, as linhas com mais de um
  valor do mesmo tipo (`linhas de lista`) e, com detector de layout, os
  blocos com as linhas de cada um (`blocos`);
- `Page.stamp`: a tarja da página, com o formato, o código, o processo, o
  signatário, a data e o protocolo, e a caixa e as linhas de onde veio. A
  tarja cujo processo não confere no dígito do CNJ não é tarja
  (`StampFormat.process_check`);
- `Page.folha`: a folha carimbada, pelo valor de `FOLHA` numa linha de
  elemento fixo, com a caixa, a linha e `in_sequence`, que diz se a folha
  segue a das outras páginas da execução;
- `process(stamps=)` e `process(folhas=)`, também em `Document.read`: os
  formatos de tarja e as formas de folha, pelo nome ou pelo objeto.
  `e-saj` e `folha` são o padrão; `pje`, `projudi-pr`, `projudi-go`,
  `eproc` e `pagina-projudi` são pontos de partida medidos em poucas
  páginas;
- `StampFormat`, `STAMP_FORMATS`, `FOLHA_FORMATS` e os formatos em
  `docaudit.policies`; `Run.stamps` e `Run.folhas`;
- `process(spans=True)`: cada `Entity.span` diz o começo e o fim do valor no
  texto das linhas dele; desligado por omissão;
- `drawn_lines_of`: as linhas da camada com a posição de cada uma na ordem
  de desenho da página, que nem sempre é a do texto do pdfium;
- numa digitalização com camada e `trust_layer="visible"`, a linha da camada
  com um id que confere e que os pixels não confirmaram entra no lugar das
  linhas dos pixels no mesmo lugar, e cada linha trocada fica em
  `Result.others` com `replaced`; a tarja e o carimbo de folha desenhados à
  vista por cima da digitalização entram do mesmo jeito (`DrawnLine.visible`);
- `RegionView.rasters`: as imagens da página que o recorte lê, para um
  leitor recusar o logotipo com o próprio limiar numa chamada só.
- `Check.alike`: a troca que leitores de famílias diferentes fazem igual.
  Nela, outra família que lê o mesmo valor inválido não prova que ele está
  impresso: a página segue ao leitor caro, e a entidade sai sem `printed`.
  O ponto no lugar da vírgula decimal de `AMOUNT_BRL` é uma;
- `AMOUNT_BRL` casa também o ponto decimal logo depois do `R$`
  (`R$ 18.77`) e no valor sozinho na linha (`0.00`);
- `AMOUNT_BRL` casa o lançamento de extrato sem `R$`, o valor seguido de
  `C` ou `D` (`1.249,01 C`);
- `DATE_VERBOSE`, a data por extenso (`1º de março de 2024`) que existe no
  calendário, em `DEFAULT_ENTITIES`, com o estado `well_formed`;
- `NFE_KEY`, `BOLETO` e `ARRECADACAO`: a chave de acesso de documento fiscal
  eletrônico, a linha digitável de boleto e o código de arrecadação da
  FEBRABAN, pelos dígitos verificadores e pelos campos fechados. Entram em
  `DEFAULT_ENTITIES` com `confirmed`, e não em `DEFAULT_SIGNALS`;
- `PIS`, `VOTER_ID`, `CNH` e `RENAVAM`, ids com dígito verificador que
  entram por escolha, em `entities=` ou como `FailsCheck` na política, e a
  tupla `IDENTIFIERS`. Um `Check` cuja forma nomeia o grupo `value` entrega
  à verificação e à entidade só esse grupo: é como a CNH e o RENAVAM casam
  depois do rótulo sem o levar no valor;
- `Result.document` (`DocumentFacts`): o que o arquivo diz de si, lido sem
  renderizar nada: produtor, criador, título, datas com fuso, versão do
  PDF, árvore de estrutura, formulário, quantas vezes foi gravado, se o
  `/ID` mudou, permissões, rótulos de página e as assinaturas declaradas
  (`Signature`, com `covers_file`). `docaudit.pdf.load_facts` e
  `Document.facts` dão o mesmo; `to_markdown(annotated=True)` abre com ele;
- `Page.hidden_fonts`: as fontes do texto invisível, quem escreveu a camada
  de uma digitalização;
- `PageDimensions.paper`: `A4`, `Letter`, `Ofício` ou `None`;
- o `PPOCR` lê em pé a página digitalizada de lado, e a linha de uma tabela
  sai inteira. `Chunk.turn` diz o giro, a caixa fica no sistema da imagem, e
  `BBox.unturned` leva a caixa da página girada para esse sistema.
  A página com a maioria das linhas altas paga duas leituras;
- `PPOCR.prepare`: baixa os pesos e abre as sessões antes da primeira leitura;
- `Result.read_by`: os leitores que deram linhas a cada página, o fato que
  `Page.substrate` não diz;
- `Result.verification`: por página e por verificação, quantos valores em cada
  estado, e quantas falhas estão impressas no documento.

### Mudado

- `Result.cited` compara só letras e dígitos: a pontuação, as aspas e o
  espaço deixam de contar; um dígito trocado continua a não conferir;
- `RoutingDecision.incomplete` diz que um leitor falhou e nenhum outro leu no
  lugar dele, também na página em que a camada de texto trouxe a tarja;
- na página com duas tarjas ou duas folhas fixas, vale a última desenhada,
  pela ordem de desenho do PDF;
- a tarja e a folha são lidas antes de reordenar as linhas pelo layout.

### Corrigido

- O `PPOCR` com a instalação quebrada, como um `cv2` sem `resize`, para o
  documento com `ImportError`, em vez de falhar página a página em
  silêncio;
- numa página lida de lado, `mark_furniture` julga a linha como ela é lida: a
  linha repetida no meio da leitura deixa de sair com `furniture`;
- numa página lida de lado, `strong` relê a imagem em pé, e a linha relida traz o
  giro em `Chunk.turn`, com a caixa no sistema da imagem;
- o peso do `PPOCR` que falta para o documento ao carregar, em vez de falhar
  página a página;
- a folha lida nos pixels vale quando a camada tem outra linha fixa sem
  folha, como a tarja;
- o corpo desenhado em contornos de glifo com curva vai para `Page.unread`
  e é lido pelos pixels, também quando o desenho tem texto dentro, como uma
  tarja ou um cabeçalho. Contam os caminhos preenchidos com curva que nenhum
  texto toca, quando são muitos: o logotipo e o fundo arredondado de uma
  célula ficam lidos.

## [0.1.0] - 2026-10-20

A primeira versão.

- `process()` classifica o substrato de cada página, lê com a cascata barata
  (camada de texto, depois `PPOCR`), aponta com verificações por regra as
  linhas provadamente erradas e relê essas linhas com outra família de OCR
  ou com o leitor caro; cada chunk diz página, caixa e leitor de origem;
- o texto numa fonte sem mapa para Unicode sai da camada de texto e vai
  para o leitor de pixels; a página com texto mal decodificado escala;
- `EvidenceRouter(min_failures=)` escala a página por valores que falham; a
  leitura cara passa pelas mesmas verificações que a barata, e a linha cara
  que perde um valor que conferia é recusada;
- `PPOCR` traz os pesos `v5-latin` e `v6-medium`, aceita um reconhecedor
  próprio (`rec=`, `keys=`) e roda no ONNX Runtime, no CUDA ou no OpenVINO
  (`engine=`, `"auto"` por padrão) (`docs/configuration.md`);
- `CPF`, `CNPJ`, `CNJ`, valores em reais e em moedas anteriores ao real,
  datas com dia da semana e a folha dos autos saem em `Result.entities`, com
  estado, página, caixa e linhas de origem (`docs/entities.md`);
- `Result.run` diz com que política, leitores, argumentos e versões o
  resultado saiu; `Result.others` guarda a leitura de outro leitor ao lado
  da linha que ela substituiu ou não explicou;
- `Result.refs()`, `Result.cited()` e `to_markdown(annotated=True)` entregam
  a leitura a um modelo com cada conclusão citável (`docs/agent.md`);
- `Document` e `Doubt`, a superfície para um agente; `Chunk.furniture`
  marca cabeçalho, rodapé e tarja; `Page.document` dá o código da peça na
  tarja do e-SAJ;
- `VLM` com os presets `glm-ocr` e `paddleocr-vl`, e `ModelCallCache` para
  as chamadas pagas.
