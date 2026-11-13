# Glossário

Cada termo tem um sentido só em toda a documentação. Quando há um nome no
código, ele vem ao lado. A explicação longa fica na página ligada.

## Leitura

### Etapa barata { #etapa-barata }

A primeira etapa de leitura. Toda página passa por ela, com a
[cascata](#cascata) de [leitores baratos](#leitor-barato). O tempo dela fica
em `spent.seconds_cheap`, e a página que só passou por ela tem
`RoutingDecision.tier == "cheap"`.

### Etapa cara { #etapa-cara }

A segunda etapa, que só existe com um [leitor caro](#leitor-caro). Lê as
páginas que a [política](#politica) [encaminhou](#encaminhar), dentro do
[teto](#teto). O tempo dela fica em `spent.seconds_strong`.

### Leitor barato { #leitor-barato }

Quem lê na [etapa barata](#etapa-barata): a camada de texto, o PP-OCR ou o
Tesseract, por exemplo. Os leitores baratos vão em `process(cheap=...)`.

### Leitor caro { #leitor-caro }

Quem relê a página encaminhada na [etapa cara](#etapa-cara). Pode ser um OCR
maior, um modelo de visão e linguagem na própria máquina ou um serviço
[externo](#externo). Vai em `process(strong=...)`. Sem ele, nenhuma página
[escala](#escalar).

### Cascata { #cascata }

A lista ordenada de [leitores baratos](#leitor-barato), em
`process(cheap=...)`. Cada leitor tenta a página na ordem, e vale a primeira
leitura não vazia. O padrão é `("text_layer", "ppocr")`. Ver
[Cascata e elementos fixos](concepts/cascade.md).

### Família { #familia }

Um motor de OCR de outra arquitetura e de outro treino. Os erros de duas
famílias não coincidem. O PP-OCR e o Tesseract são famílias diferentes; a
[camada de OCR](#camada-de-ocr) de uma digitalização conta como uma família.
A camada que o Tesseract escreveu, com a fonte `GlyphLessFont`, é da mesma
família que o Tesseract, e não relê o que ele leu.

### Releitura por outra família { #releitura-por-outra-familia }

A releitura da página encaminhada por uma [verificação](#verificacao), feita
por um leitor de outra [família](#familia) antes do
[leitor caro](#leitor-caro). Separa o erro impresso no documento do erro de
leitura. O mesmo valor inválido nas duas leituras é erro impresso. Um valor
válido no mesmo lugar troca a linha. Vai em `process(confirm=...)`. Não tem
relação com o [estado](#estado) `confirmed`. Ver
[Política, conferência e escalada](concepts/policy.md).

### Externo { #externo }

Um leitor que envia a página para fora da máquina, como um modelo num
servidor de outro host. Declara `external = True`, e `process()` recusa usá-lo
sem `allow_external=True`. Ver [Segurança dos dados](security.md).

### Recorte { #recorte }

O pedaço da página que um leitor relê, e não a página inteira. O leitor caro
recebe o recorte das linhas que falharam com `process(reread="region")`;
`Document.crop` devolve a imagem de um recorte.

### Detector de layout { #detector-de-layout }

O modelo que divide a página em [regiões de layout](#regiao-de-layout), com
rótulo, caixa e ordem de leitura. É o `PPDocLayout`, do extra `layout`.

### Detecção de texto { #deteccao-de-texto }

A etapa do PP-OCR que acha as linhas de texto na imagem, antes de
reconhecê-las.

### Região de layout { #regiao-de-layout }

O que o [detector de layout](#detector-de-layout) devolve: uma área da
página com rótulo (texto, tabela, título, carimbo) e caixa. Também se diz
bloco de layout. Tipo `Region`. Não confundir com o [bloco](#bloco) de
`Result.records()`.

## Política e conferência

### Política { #politica }

A regra que decide que páginas [encaminhar](#encaminhar) ao
[leitor caro](#leitor-caro). Vai em `process(policy=...)`; o contrato é
`TriagePolicy`. As políticas prontas são `all_cheap`, `all_strong` e
`evidence`. Ver [Política, conferência e escalada](concepts/policy.md).

### Decisão da política { #decisao-da-politica }

O destino e o motivo de cada página, com os passos que `process` deu nela.
Tipo `RoutingDecision`, em `Result.decisions`.

### Encaminhar { #encaminhar }

O que a [política](#politica) faz com a página que deve ir ao
[leitor caro](#leitor-caro): `RoutingDecision.tier == "strong"`. Encaminhar
não é [escalar](#escalar). Sem `strong=`, ou com o [teto](#teto) cheio, a
página encaminhada fica com a leitura barata.

### Escalar { #escalar }

O que acontece quando o [leitor caro](#leitor-caro) lê de fato a página. O
número de páginas escaladas fica em `spent.pages_strong`.

### Sinal { #sinal }

Uma função que conta, numa página, as evidências de que a leitura está
errada. Zero quer dizer nenhuma. Contrato `Signal`; exemplos prontos:
`EmptyRead`, `GarbledText`, `FailsCheck`. A política `evidence` encaminha a
página em que algum sinal disparou.

### Verificação { #verificacao }

A forma impressa de um campo e a regra de validade dele, como o CPF com o
dígito verificador. Tipo `Check`. A mesma verificação serve de [sinal](#sinal)
(`FailsCheck(check)`) e de extrator de [entidades](#entidade). Ver
[Declarar os campos do seu documento](how-to/checks.md).

### Conferir { #conferir }

Aplicar a regra de uma [verificação](#verificacao) a um valor lido. Também
se confere uma citação: a linha que um agente cita contra o texto lido.

### Entidade { #entidade }

Um valor que uma [verificação](#verificacao) achou no texto lido, com o
[estado](#estado), a página, a caixa e as linhas de origem. Tipo `Entity`,
em `Result.entities`. Ver [Entidades padrão](entities.md).

### Estado { #estado }

O que a regra diz do valor de uma [entidade](#entidade). Tipo `EntityState`:

| estado | quer dizer |
|---|---|
| `confirmed` | a regra tem redundância e confere, como o dígito verificador de um CPF |
| `well_formed` | a forma e a regra passam, sem redundância, como uma data que existe |
| `failed` | a regra falha: erro de leitura ou erro impresso no documento |

### Identificador { #identificador }

Um número com dígito verificador: CPF, CNPJ, PIS e outros. Os opcionais ficam
em `IDENTIFIERS`.

### Teto { #teto }

O limite opcional do [leitor caro](#leitor-caro), em páginas e em segundos.
Tipo `Budget`, em `process(budget=...)`. Tokens e dólares são relatados em
`Result.spent`, não limitados.

## Página e documento

### Substrato { #substrato }

De onde veio a [camada de texto](#camada-de-texto) da página. Tipo
`Substrate`, com três valores: `born_digital`
([nato-digital](#nato-digital)), `searchable_scan` (digitalizada com
[camada de OCR](#camada-de-ocr)) e `image_only` (digitalizada sem texto).
Ver [Substrato](concepts/substrate.md).

### Nato-digital { #nato-digital }

A página cujo texto o programa que gerou o PDF compôs, como a de um editor
de texto. `Substrate.BORN_DIGITAL`. A camada de texto dela é exata.

### Digitalizada { #digitalizada }

A página que é a imagem de uma folha de papel. `Substrate.SEARCHABLE_SCAN`
quando tem [camada de OCR](#camada-de-ocr), `Substrate.IMAGE_ONLY` quando não
tem texto nenhum.

### Camada de texto { #camada-de-texto }

Todo texto embutido no PDF, à vista ou escondido. O leitor `text_layer` a lê
sem renderizar a página.

### Texto à vista { #texto-a-vista }

O texto que aparece na página impressa.

### Texto escondido { #texto-escondido }

O texto que está no PDF mas não aparece na página impressa: desenhado sem
tinta, ou coberto por uma imagem.

### Camada de OCR { #camada-de-ocr }

O [texto escondido](#texto-escondido) que um motor de OCR pôs sobre uma
digitalização, para que ela possa ser buscada. A qualidade dela é
desconhecida.

### Raster não lido { #raster-nao-lido }

Uma imagem da página que nenhuma camada de texto cobre, como um logotipo ou
uma assinatura digitalizada. As caixas ficam em `Page.unread`.

### Página { #pagina }

A página do PDF e a imagem dela. Tipo `Page`; o índice começa em zero.

### Folha { #folha }

O número da folha dos autos, carimbado na página. Não é o índice da
[página](#pagina). Tipo `Folha`, em `Page.folha`.

### Carimbo de folha { #carimbo-de-folha }

O carimbo que traz o número da [folha](#folha).

### Tarja { #tarja }

A faixa que o sistema eletrônico do tribunal imprime na margem, com código e
assinatura. Tipo `Stamp`, em `Page.stamp`.

### Carimbo { #carimbo }

Um carimbo físico, ou o selo na imagem. O detector de layout o rotula
`seal`.

### Peça { #peca }

Páginas seguidas com a mesma [tarja](#tarja). Tipo `Piece`, em
`Result.pieces()`.

### Autos { #autos }

O conjunto das peças de um processo judicial. Também se diz o processo.

### Elemento fixo { #elemento-fixo }

A linha que se repete no mesmo lugar em outras páginas, que não são cópia
da página dela: cabeçalho, rodapé, [tarja](#tarja). Fica no resultado com `Chunk.furniture` verdadeiro. Ver
[Cascata e elementos fixos](concepts/cascade.md).

## Resultado

### Trecho { #trecho }

A unidade de texto lido, com página, [caixa](#caixa), leitor e ordem de
leitura. Um OCR devolve um trecho por linha; um leitor por região, um
trecho por região. Tipo `Chunk`, em `Result.chunks`.

### Caixa { #caixa }

O retângulo de um trecho na página, normalizado a [0, 1], com origem no
canto superior esquerdo. Tipo `BBox`. `to_pixels` converte para o tamanho de
uma imagem.

### Bloco { #bloco }

Um grupo de fileiras vizinhas em `Result.records()`, montado só pela
posição das caixas. Tipo `Record`. Não é a
[região de layout](#regiao-de-layout).

### Fileira { #fileira }

Os trechos de um bloco que ficam na mesma altura da página, da esquerda
para a direita. A célula que cobre várias fileiras fica numa fileira só
dela. É a linha de uma tabela, montada pela geometria.

### Referência { #referencia }

O nome curto de um trecho, `p<página>:<posição>`, dado por `Result.refs()`
na ordem de leitura. É o que um modelo ou uma pessoa cita; `Chunk.id` é a
identidade estável.

### Citação conferida { #citacao-conferida }

Uma referência cuja linha contém, letra por letra e dígito por dígito, o
valor que a resposta atribui a ela. `Result.cited()` faz a conferência sem
modelo e devolve só as referências que passam.

### Dúvida { #duvida }

Uma linha lida que merece revisão: o valor que falhou uma verificação, ou
que outro leitor leu diferente, a camada de OCR ou o leitor caro, com as
outras leituras do mesmo lugar ao lado. Tipo `Doubt`, em `Document.doubts`.

### Figura { #figura }

Uma imagem numa página nato-digital, e as linhas que um leitor de pixels
leu dentro dela: a planta, a foto, o carimbo, a tabela colada como imagem.
Tipo `Figure`, em `Result.figures()`. Numa página digitalizada a folha inteira
é imagem, e não é figura.

### Leitor de pixels { #leitor-de-pixels }

Um leitor que lê a imagem renderizada, por OCR ou por modelo de visão, em
oposição à [camada de texto](#camada-de-texto), que lê o que o PDF já traz
como texto.

### Leitura cara { #leitura-cara }

O mesmo que a [etapa cara](#etapa-cara): a leitura da página pelo
[leitor caro](#leitor-caro), depois da releitura por outra família.

### Origem { #origem }

A página, a caixa, o leitor e a versão de onde saiu cada trecho. O nome do
leitor fica em `Chunk.source`, e a versão de cada leitor em `Run.versions`.
Ver [Origem e cache](concepts/provenance.md).

### Cache { #cache }

O arquivo que guarda cada leitura, `ModelCallCache`. A chave junta o
documento, a página, o DPI, o leitor e a versão de saída dele
(`output_version`). Uma segunda execução igual lê do disco. Ver
[Origem e cache](concepts/provenance.md).
