# Campos do resultado

Os campos de cada objeto do `Result`, na ordem em que saem no JSON. Um exemplo
completo está em [Formato da resposta](index.md). As assinaturas e os métodos
estão na referência da API, em [Resultado](../reference/types.md).

Toda página é contada a partir de zero, em `Page.index` e no campo `page` de
cada objeto. Toda caixa segue [a convenção de `BBox`](#bbox).

## `Page`

| campo | o que traz |
|---|---|
| `doc_id` | o identificador do documento, o mesmo de `Result.doc_id` |
| `index` | o índice da página, a partir de zero |
| `dimensions` | largura e altura em pontos e em pixels, e o DPI da renderização. A propriedade `dimensions.paper` diz `A4`, `Letter`, `Ofício` ou `None`, com 3 mm de folga em cada lado. Ela não sai no JSON |
| `substrate` | `born_digital`, `searchable_scan` ou `image_only`; ver [Substrato](../concepts/substrate.md) |
| `substrate_evidence` | os números que decidiram o substrato: `chars`, `visible_text`, `invisible_text`, `covered_text`, `unmapped_text`, `unread_regions` e, quando há imagem, `native_dpi` |
| `stamp` | a tarja achada na camada de texto, num dos formatos de `stamps=`, ou `null`; ver [`Stamp`](#stamp) |
| `folha` | a folha dos autos carimbada na página, ou `null`; ver [`Folha`](#folha) |
| `unread` | as caixas das imagens e dos desenhos que nenhuma camada de texto leu, de cima para baixo e da esquerda para a direita. Rasters que se tocam formam uma caixa só. O índice nesta lista é o que `Chunk.region` aponta |
| `hidden_fonts` | os nomes das fontes do texto escondido, sem repetição. Dizem quem escreveu a camada de OCR: o Tesseract deixa `GlyphLessFont`. Vazio numa página nato-digital |

## `Stamp`

A [tarja](../glossary.md#tarja) que o sistema eletrônico do tribunal imprime na
margem de cada página de uma peça.

| campo | o que traz |
|---|---|
| `format` | o nome do `StampFormat` que casou: `e-saj` por padrão |
| `code` | o código de conferência, que identifica a peça juntada. Muda onde começa outra peça |
| `process` | o número do processo que a tarja cita, como impresso |
| `signer` | quem assinou, como impresso |
| `at` | quando a peça foi protocolada ou liberada nos autos. É a hora local impressa, sem fuso, salvo quando o formato declara `tz` |
| `protocol` | o número do protocolo. No e-SAJ, `null` no ato que o juízo liberou nos autos |
| `bbox`, `chunk_ids` | a caixa e as linhas da tarja |

Fora `code`, o campo que o formato não imprime sai `null`. Na página copiada
de outro processo, vale a última tarja desenhada. A tarja cujo número de
processo falha o dígito do CNJ não conta como tarja. Um formato sem número CNJ
desliga essa conferência com `process_check=None`.

## `Folha`

A [folha](../glossary.md#folha) é o número que o tribunal carimba na página. Ela
não coincide com o índice da página.

| campo | o que traz |
|---|---|
| `value` | o número da folha, sem o ponto de milhar |
| `bbox`, `chunk_ids` | a caixa e a linha do carimbo |
| `in_sequence` | `true` quando a folha segue as das outras páginas da execução |

`folha.value` vem de uma forma de `folhas=` numa linha de elemento fixo. No
corpo da página, a mesma forma é uma citação e sai só em `entities`. `folha`
sai `null` sem carimbo, no verso e numa execução de uma página só.

`in_sequence` compara a diferença entre a folha e o índice da página com a
diferença mais comum da execução. Um documento juntado com numeração própria
sai com a numeração dele, e `in_sequence` o aponta. Num PDF que junta peças de
vários processos, vale a sequência do maior trecho. A regra supõe uma página
por folha: num processo digitalizado com o verso de cada folha, nenhuma folha
segue a sequência.

## `Chunk`

O [trecho](../glossary.md#trecho) é a unidade de texto lido.

| campo | o que traz |
|---|---|
| `id` | o identificador determinístico do trecho; ver [O identificador](#o-identificador) |
| `page` | o índice da página |
| `bbox` | a caixa do trecho |
| `text` | o texto como o leitor o devolveu, com as quebras de linha |
| `source` | o nome do leitor que leu o trecho |
| `confidence` | a confiança média que o motor deu, em `[0, 1]`, ou `null` |
| `reading_order` | a posição do trecho na ordem de leitura da página, ou `null` |
| `turn` | os graus, no sentido anti-horário, que o leitor girou a página para ler a linha em pé: `0`, `90` ou `270`. A caixa não gira |
| `kind` | o tipo da região de layout de onde o texto veio, como `text`, `table` ou `paragraph_title`, quando há detector de layout |
| `line_break_hyphens` | os índices em `text` dos hífens que estavam numa quebra de linha do PDF, na camada de texto. O hífen fica no texto, e quem lê decide se junta as metades. A palavra que continua noutra coluna, ou depois de outra linha, sai em dois trechos, o primeiro terminando no hífen |
| `region` | o índice em `Page.unread` do raster de onde a linha veio, quando um leitor de pixels a leu num raster que a camada de texto não leu; `null` nos outros casos |
| `furniture` | `true` no [elemento fixo](../glossary.md#elemento-fixo): a linha que se repete, no mesmo lugar, em outra página lida que não é cópia desta, numa sequência a partir do alto ou do pé da folha, ou na vertical da margem. São o cabeçalho, o rodapé e a tarja. A linha fica no resultado |

A unidade depende do leitor. A camada de texto, o Tesseract e o PP-OCR
devolvem uma linha por trecho. O leitor `vlm` com detector de layout devolve
uma região por trecho, e sem detector devolve a página inteira num trecho. A
tabela que o `vlm` lê vem num trecho só, uma linha de texto por linha da
tabela, com as células separadas por ` | `.

`confidence` é um sinal cru do motor. A escala muda de um motor para outro, e
a biblioteca não aplica limiar sobre ela.

### `BBox`

`BBox` guarda `x0`, `y0`, `x1` e `y1` em `[0, 1]`, com origem no canto superior
esquerdo da página como ela é exibida, já com o `/Rotate` do PDF aplicado. A
caixa não guarda pixels. Para recortar uma imagem, converta na hora, com o
tamanho da imagem que você tem:

```python
import io

from PIL import Image

from docaudit import Document

with Document("mandado.pdf", cheap=["text_layer"]) as doc:
    result = doc.read()
    image = Image.open(io.BytesIO(doc.render(0)))  # a página 0 em PNG

chunk = result.chunks[0]
x0, y0, x1, y1 = chunk.bbox.to_pixels(image.width, image.height)
```

`BBox.from_pixels(x0, y0, x1, y1, width_px=..., height_px=...)` faz o caminho
inverso, para um leitor que recebe caixas em pixels do motor. Os pontos do PDF
saem de `Page.dimensions.width_pt` e `height_pt`.

### O identificador

`Chunk.make_id` é o SHA-256 de cinco coisas: o `doc_id` com o DPI, o índice da
página, a caixa, o nome do leitor e o texto. O mesmo documento, lido pelos
mesmos leitores, gera os mesmos `id` em qualquer ambiente. O texto entra porque
dois trechos podem ocupar a mesma caixa. O índice entra porque um documento
pode ter duas páginas de bytes idênticos.

O `id` não leva a versão do leitor. O mesmo texto, na mesma caixa, lido pelo
mesmo leitor, tem o mesmo `id` em qualquer versão. Assim a citação de uma linha
sobrevive a uma troca de pesos que não mudou a leitura. A versão fica em
[`Run.versions`](#run).

## `Entity`

A [entidade](../glossary.md#entidade) é um valor achado por uma verificação.

| campo | o que traz |
|---|---|
| `kind` | o nome do campo, que é o `name` do `Check`: `CPF`, `CNPJ`, `CNJ`, `valor em reais`, `data`, ou o nome de um `Check` seu |
| `value` | o valor como impresso, com os espaços colapsados |
| `state` | `confirmed`, `well_formed` ou `failed`; ver [Os três estados](../entities.md#os-tres-estados) |
| `page` | o índice da página |
| `bbox` | a menor caixa que contém as linhas do valor |
| `chunk_ids` | os `id` das linhas que o valor toca: duas quando ele quebra entre linhas |
| `span` | com `process(spans=True)`, o começo e o fim do valor no texto das linhas de `chunk_ids` unidas por quebra de linha; `null` por padrão |
| `printed` | num valor `failed`, quem mostra que o erro é do documento; `null` quando o erro pode ser de leitura |

`printed` vale `text_layer` quando o valor veio da camada à vista de uma página
nato-digital, onde não há leitor que erre. Vale o nome de um leitor quando
outra família leu o mesmo valor inválido no mesmo lugar.

## `Figure`

Uma imagem numa página nato-digital: a planta, a foto, a captura de tela, a
tabela colada como imagem. Não é campo do `Result`: sai de `result.figures()`,
a partir de `Page.unread` e do `Chunk.region` de cada linha. Numa página
digitalizada a folha inteira é imagem, e ela não conta como figura.

| campo | o que traz |
|---|---|
| `ref` | `p<página>:f<índice>`, o nome com que um modelo cita a figura |
| `page` | o índice da página |
| `index` | o índice da imagem em `Page.unread` |
| `bbox` | a caixa da imagem |
| `chunk_ids` | as linhas que um leitor de pixels leu dentro dela; vazio numa foto ou numa assinatura sem texto |

`Document.crop(figure.page, figure.bbox)` devolve o PNG da figura, no DPI em
que os leitores a viram.

## `Record`

Um [bloco](../glossary.md#bloco) de linhas vizinhas de uma página, agrupadas só
pela posição das caixas. Não é campo do `Result`: sai de `result.records()`.
Nenhum modelo roda.

| campo | o que traz |
|---|---|
| `ref` | `p<página>:b<índice>`, o nome com que um modelo cita o bloco |
| `page` | o índice da página |
| `index` | a posição do bloco na página, de cima para baixo |
| `bbox` | a caixa que contém as linhas do bloco |
| `rows` | as fileiras, cada uma com o texto das células. A linha de prosa é uma fileira de uma célula |
| `chunk_ids` | as linhas do bloco, fileira a fileira |

Duas linhas que se sobrepõem na vertical em mais da metade da menor ficam na
mesma fileira, da esquerda para a direita. A linha que cobre duas linhas que
não se tocam, como uma célula mesclada ou uma tarja vertical na margem, fica
numa fileira sozinha, na posição dela. As fileiras seguidas cujo vão não
passa de `gap` vezes a altura mediana das linhas da página ficam no mesmo
bloco. As propriedades `text` e `tabular` não saem no JSON. `record.text` dá
as fileiras com as células separadas por ` | `. `record.tabular` diz se alguma
fileira tem mais de uma célula.

Numa página em duas colunas sem detector de layout, as linhas lado a lado saem
como células de uma fileira. Nesse caso, `process(layout=)` dá a ordem por
bloco.

## `Piece`

A [peça](../glossary.md#peca): páginas seguidas com a mesma tarja. Sai de
`result.pieces()`, a partir de `Page.stamp`. As páginas seguidas sem tarja
formam uma peça sem código. A biblioteca não diz se a peça é petição, decisão
ou certidão.

| campo | o que traz |
|---|---|
| `index` | a posição da peça no documento |
| `pages` | os índices das páginas, seguidos |
| `stamp` | a tarja da primeira página; `None` sem tarja |

`piece.code` é uma propriedade, e não sai no JSON. Ela dá o `Stamp.code` comum
às páginas, ou `None` sem tarja.

## `OtherReading`

Outra leitura do mesmo lugar de uma linha do resultado. Sai em
`result.others`, e `Document.doubts()` junta a de cada linha à dúvida dela.

| campo | o que traz |
|---|---|
| `line` | o `id` da linha do resultado |
| `reading` | o `Chunk` do outro leitor, com caixa, texto e `source` |
| `same` | `true` quando o outro leitor leu o mesmo valor inválido. Só prova o erro impresso quando vem de outra família: `confirm=` ou a camada de OCR. A linha recusada do leitor caro repete o valor e não prova nada. Sempre `false` numa leitura substituída |
| `replaced` | `true` quando `reading` estava no resultado e saiu: `line` é a linha que entrou no lugar dela |
| `check`, `value` | numa linha que não falha, o campo e o valor que a outra família lê diferente |

Há três casos:

- a releitura que não conferiu fica ao lado da linha que continuou no
  resultado;
- a linha da camada de OCR que lê outro valor em reais também fica ao lado,
  com `check` e `value`;
- a leitura que saiu porque a releitura por outra família conferiu, ou porque
  o leitor caro leu ali, fica ao lado da linha que a substituiu, com
  `replaced`.

Quando o leitor caro lê a página inteira num trecho só, essas linhas apontam
para esse trecho. `Document.doubts()` deixa as leituras substituídas de fora.

## `RoutingDecision`

A [decisão da política](../glossary.md#decisao-da-politica) de uma página.

| campo | o que traz |
|---|---|
| `page` | o índice da página |
| `tier` | `cheap` ou `strong`: o destino que a política deu à página |
| `reason` | o motivo, numa frase, para quem lê |
| `signals` | a contagem de cada sinal que disparou, pelo nome do sinal |
| `steps` | o que `process()` fez com a página, uma frase por passo, na ordem |
| `failures` | cada leitor que falhou na página, como `<leitor>: <mensagem>`: o da cascata que passou a vez ao seguinte, o da releitura, o leitor caro. Vazio quando nenhum falhou |
| `incomplete` | `true` quando um leitor falhou e nenhum outro leu no lugar dele: as linhas, se houver, são só parte da página. `false` quando o seguinte da cascata leu, e quando só o leitor caro falhou e a leitura barata ficou. Numa política que decide antes de ler, como `all_strong`, a página que o leitor caro recusou não tem leitura barata, e sem linha nenhuma sai `true` |
| `seconds` | os segundos de parede de cada etapa que tocou a página: `cheap`, com a detecção de layout, `confirm` e `strong`. A leitura do cache conta o tempo que levou |

`tier` é o veredito da política, e não o que rodou. Sem leitor caro
(`strong=None`), uma página pode sair com `strong` e ter sido lida só na etapa
barata. É o modo de ensaio de uma política. `spent.pages_strong` conta as
páginas que o leitor caro de fato leu.

`seconds` diz onde está o custo de uma página sem medir por fora. O total da
execução está em `spent`.

## `Spent`

O que a chamada gastou, relatado e não limitado. Todas as chaves saem sempre,
zeradas quando a etapa não rodou.

| chave | o que conta |
|---|---|
| `pages_total` | as páginas processadas |
| `pages_cheap` | as páginas lidas na etapa barata |
| `pages_strong` | as páginas lidas pelo leitor caro |
| `pages_cheap_cached` | das páginas de `pages_cheap`, as que vieram do cache |
| `pages_cheap_failed` | as páginas em que algum leitor barato falhou e passou a vez ao seguinte |
| `regions_cheap` | as páginas em que o leitor seguinte da cascata leu, como região, as imagens que a camada de texto não leu |
| `regions_strong` | as páginas em que o leitor caro leu só os recortes das linhas que falharam |
| `lines_strong_rejected` | as linhas do leitor caro que não entraram no lugar das baratas: perderam um valor que conferia, ou não explicaram o valor que falhou |
| `pages_strong_cached` | das páginas de `pages_strong`, as que vieram do cache |
| `pages_strong_failed` | as páginas que o leitor caro recusou. Elas ficam com a leitura barata quando a política a fez, como `evidence` |
| `pages_confirmed` | as releituras por outra família antes do leitor caro. Numa `SEARCHABLE_SCAN` com `confirm=`, a página pode contar duas: a camada de OCR e o leitor de `confirm=` |
| `pages_confirmed_same` | as páginas em que a releitura trouxe os mesmos valores inválidos: o erro é do documento |
| `pages_confirmed_fixed` | as páginas em que a releitura trouxe um valor que confere no mesmo lugar |
| `pages_confirm_cached` | das releituras de `pages_confirmed`, as que vieram do cache |
| `pages_layout_cached` | as detecções de layout que vieram do cache |
| `seconds_cheap`, `seconds_confirm`, `seconds_strong` | o tempo de parede de cada etapa. A detecção de layout entra na etapa que renderizou a página |
| `seconds` | os segundos da chamada inteira |
| `calls`, `tokens_in`, `tokens_out`, `usd` | o que os leitores `Metered` contaram; `null` sem nenhum |

Um leitor que implementa `Metered`, como o `vlm`, preenche `calls`,
`tokens_in`, `tokens_out` e, quando recebeu preços, `usd`. Contam o leitor
caro, os baratos e o de `confirm=`. O valor é a diferença entre o início e o
fim da chamada, e por isso o que o cache serviu não conta. As contagens de
páginas e os segundos incluem o que o cache serviu: os `*_cached` dizem
quanto foi. A biblioteca não
traz tabela de preços: o preço é de quem chama, e muda com o tempo.

## `DocumentFacts`

O que o arquivo diz de si, lido do trailer, do catálogo e do dicionário de
informações, sem renderizar nada. Sai em `Result.document`.
`docaudit.pdf.load_facts()` devolve o mesmo sem classificar página nenhuma, e
`Document.facts` o guarda.

| campo | o que traz |
|---|---|
| `producer`, `creator` | o programa que gravou o arquivo por último e o que o criou, ou `null` |
| `title`, `author`, `subject`, `keywords` | os campos do `/Info`, ou `null` |
| `created_at`, `modified_at` | as datas do `/Info`, com o fuso que o arquivo declara |
| `pdf_version` | `1.4`, `1.7`; `null` quando o arquivo não a declara |
| `tagged` | se o PDF tem árvore de estrutura, isto é, se a ordem de leitura é declarada |
| `form` | `none`, `acroform`, `xfa_full` ou `xfa_foreground` |
| `saves` | quantas vezes o arquivo foi gravado, pelos `startxref`: uma na criação e mais uma por atualização incremental. O trailer extra de um arquivo linearizado não conta. `null` sem o arquivo, como numa imagem |
| `identifier_changed` | se o `/ID` mutável difere do permanente, isto é, se o arquivo foi regravado; `null` sem `/ID` |
| `restricted` | se o arquivo nega alguma permissão, como copiar texto |
| `page_labels` | se o arquivo declara rótulos de página próprios |
| `signatures` | as assinaturas digitais declaradas; ver abaixo |

`producer` e `creator` são de quem gravou o arquivo por último. Uma ferramenta
que divide um PDF em páginas põe o próprio nome e perde a assinatura e a data
do original. O que estes campos provam, e o que não provam, está em
[Origem e cache](../concepts/provenance.md).

### `Signature`

| campo | o que traz |
|---|---|
| `sub_filter` | o padrão da assinatura, como `adbe.pkcs7.detached` ou `ETSI.CAdES.detached` |
| `signed_at` | quando o arquivo diz ter sido assinado, com o fuso declarado |
| `reason` | o motivo declarado, ou `null` |
| `mdp_permission` | a permissão DocMDP: `0` sem certificação, `1` nenhuma mudança, `2` formulários e assinaturas, `3` também anotações |
| `covers_file` | se o `/ByteRange` chega ao fim do arquivo, isto é, se nada foi gravado depois da assinatura |

A assinatura é lida como o arquivo a declara. O pdfium não confere a
criptografia, e o signatário fica no pacote PKCS#7, que a biblioteca não abre.

## `Run`

Com que leitores, em que versão e com que argumentos o resultado saiu. Basta
para refazer a leitura, e para saber depois que pesos, motor e dispositivo
leram cada linha. As páginas lidas estão em `Result.pages`.

| campo | o que traz |
|---|---|
| `started_at` | o início da execução, em UTC |
| `policy` | o nome da política |
| `budget` | o teto do leitor caro: `max_strong_pages`, `max_strong_fraction` e `max_seconds` |
| `cheap` | os leitores da cascata, na ordem |
| `confirm`, `strong` | o leitor da releitura por outra família e o leitor caro, ou `null` |
| `reread`, `trust_layer`, `dpi` | os argumentos de mesmo nome de `process()` |
| `entities` | os nomes das verificações de `Result.entities`, na ordem |
| `stamps` | os nomes dos formatos de tarja procurados, na ordem |
| `folhas` | os nomes das formas de folha procuradas, na ordem |
| `spans` | se `Entity.span` foi pedido |
| `min_raster_fraction` | o argumento de mesmo nome de `process()` |
| `versions` | o `output_version` de cada leitor que leu alguma linha do resultado, pelo nome, e o do detector de layout na chave `layout` |

`versions` liga cada linha ao modelo que a leu: o `source` de cada trecho, e o
de cada leitura em `others`, é uma chave dele. A versão é a mesma que entra na
chave do cache. Ela diz o que muda a leitura sem mudar o nome do leitor:

| leitor | o que a versão traz |
|---|---|
| `text_layer` | a versão do pypdfium2 |
| `tesseract` | a versão do binário, o idioma e as opções |
| `ppocr` | os pesos, ou o hash do detector próprio (`det=<hash>`) e o do reconhecedor próprio e do dicionário, a versão do RapidOCR, e o motor quando não é o ONNX Runtime na CPU (`onnxruntime`) |
| `vlm` | o modelo servido, o conjunto de prompts, o detector de layout e o esforço de raciocínio |

Dois leitores de mesmo nome em papéis diferentes, como dois `PPOCR` em motores
diferentes, não se distinguem pela linha. Nesse caso, `versions` guarda a
versão do primeiro, na ordem cascata, camada, releitura e leitor caro.

O leitor que não leu nenhuma linha do resultado não entra em `versions`, mas
continua em `cheap`, `confirm` ou `strong`, pelo nome. A razão é o custo: sem
`served=`, a versão de um `vlm` pergunta ao servidor, e um leitor caro que
nunca foi chamado não paga essa pergunta.
