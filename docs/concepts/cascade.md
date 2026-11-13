# Cascata e elementos fixos

Na [etapa barata](../glossary.md#etapa-barata), quem lê é a [cascata](../glossary.md#cascata): uma lista
ordenada de leitores baratos, declarada por quem chama.

```python
import docaudit
from docaudit.backends.ppocr import PPOCR

result = docaudit.process(
    "documento.pdf",
    cheap=["text_layer", PPOCR()],  # o padrão
)
```

## A primeira leitura não vazia

A cascata é percorrida na ordem declarada, e vale a primeira leitura não
vazia. A camada de texto é um leitor como os outros. Ela lê toda página com
texto embutido, uma linha por [trecho](../glossary.md#trecho). Numa página `IMAGE_ONLY` ela volta
vazia, e o leitor seguinte lê os pixels.

A linha da camada é a que o pdfium monta, e não um retângulo por letra. Um
gerador que posiciona cada letra isolada faria "Banco" virar cinco trechos.

Um leitor que falha numa página, com `RuntimeError`, conta como leitura
vazia. A cascata passa ao seguinte, a falha fica em
`RoutingDecision.failures` e `process()` emite um `RuntimeWarning`.

Reordenar, encurtar ou trocar a cascata é argumento de chamada. Nenhuma
mudança de código é necessária.

## A camada de uma digitalização com OCR

Numa página [`SEARCHABLE_SCAN`](substrate.md#a-classe-do-meio), a camada de
texto veio de um motor de OCR (reconhecimento óptico de caracteres)
desconhecido. Por padrão,
`trust_layer="visible"`, essa camada não é a leitura: o leitor de pixels
seguinte da cascata lê a página. A camada fica para depois, como outra
leitura já paga. Ela serve a quatro coisas:

- **Primeira [família](../glossary.md#familia) da releitura.** Antes de `confirm=`, a camada relê,
  sem custo, a página que uma verificação [encaminhou](../glossary.md#encaminhar) ao
  [leitor caro](../glossary.md#leitor-caro). Ver
  [Política](policy.md#reler-com-outra-familia-antes-do-leitor-caro).
- **Identificador que confere.** A linha da camada com um valor que uma
  verificação com redundância confirma (CPF, CNPJ, número CNJ do processo judicial), e que os
  pixels não confirmaram, entra no resultado. Ela fica com `source`
  igual a `text_layer`, no lugar das linhas dos pixels no mesmo lugar da
  página. Cada linha trocada vai para `Result.others`, com `replaced`.
- **Tarja e folha.** A [tarja](../glossary.md#tarja) e o carimbo de folha que o tribunal desenha à
  vista por cima da digitalização são texto exato. Entram da mesma forma,
  no lugar das linhas dos pixels.
- **Valor em reais.** Um valor em reais não tem dígito verificador. Quando
  a linha da camada no mesmo lugar lê outro número, ela vai para
  `Result.others`, com `check` e `value`. Isso só aponta a diferença: não
  corrige a linha nem encaminha a página.

Uma camada que discorda dos pixels sem deixar valor impossível, fora esses
casos, passa sem que nenhum sinal a veja. Com `trust_layer="always"`, a
camada é lida como está, e só a evidência no texto encaminha a página.

## Rasters que a camada não leu

Um leitor que devolve texto sem pedir os pixels, como a camada de texto,
deixa sem ler o que está em [`Page.unread`](substrate.md#o-que-nenhuma-camada-leu).
O leitor seguinte da cascata lê esses rasters:

1. Cada raster ganha uma folga de `RASTER_MARGIN` em volta. O
   [recorte](../glossary.md#recorte)
   justo corta o texto na borda, e a detecção de texto parte a linha ali.
2. Os recortes com folga que se tocam viram um recorte só. Assim o leitor
   não lê a mesma linha duas vezes.
3. O recorte que cobre a página inteira é lido como a página, com a mesma
   chave de cache.
4. Ficam as linhas cujo centro cai num raster e em nada já lido. O rodapé
   carimbado sobre a digitalização já veio da camada.

`Result.spent.regions_cheap` conta as páginas lidas assim. Se o leitor
seguinte falha num desses recortes, a página sai com
`RoutingDecision.incomplete`.

`process(min_raster_fraction=)` deixa de fora o raster menor que essa
fração da página. O logotipo e o brasão do cabeçalho custariam uma leitura
de pixels sem linha útil. O raster fica em `Page.unread` e em
`Result.figures()`, sem linha. O parâmetro existe só em `process()`, e o
padrão, `0.0`, lê todos os rasters.

!!! warning "`RASTER_MARGIN` e `min_raster_fraction` não são calibrados"
    A folga é um ponto de partida. A fração que separa um logotipo de uma
    figura com texto depende do acervo. Meça nos seus documentos antes de
    mudar qualquer dos dois.

Cada linha lida assim diz em `Chunk.region` o índice do raster em
`Page.unread`. Ela entra na ordem de leitura no lugar do raster: antes da
primeira linha da camada cujo topo fica abaixo do topo do raster. Numa
digitalização inteira com o rodapé carimbado por cima, o corpo vem antes
do rodapé. Numa página nato-digital com uma figura no meio, a figura fica
entre o texto de cima e o de baixo.

## Ordem de leitura por layout

Um OCR por linha devolve as linhas pela altura na página. Numa página em
duas colunas, como a de um diário oficial ou de um acórdão, isso intercala
as colunas. A linha de um valor sai seguida da linha de um endereço da
outra coluna, e quem lê o texto perde o fio. A camada de texto de um PDF,
por sua vez, vem na ordem em que foi gravada, e há arquivos em que ela
começa pelo rodapé.

`process(..., layout=PPDocLayout(drop=()))` ordena as linhas com o
[detector de layout](../glossary.md#detector-de-layout). As regras são
estas:

- A ordem é refeita depois de todas as leituras. Vale para a linha barata,
  para a linha que o leitor caro pôs no lugar e para a camada de texto.
- Cada linha vai ao bloco de layout que contém o seu centro, ou ao mais
  próximo.
- Os blocos saem na ordem do detector, e as linhas de cada bloco saem de
  cima para baixo.
- A linha recebe o rótulo do bloco em `kind` quando o leitor não deu um.
- Numa página sem bloco nenhum, a ordem de cada leitor fica como veio.

O porquê de `drop=()` está em [Configuração](../configuration.md). A
detecção roda uma vez por página, na mesma renderização da leitura, e o
tempo dela entra na etapa em que a página foi renderizada. Ver
[Desempenho](../performance.md).

## Os elementos fixos da página

O cabeçalho do tribunal, o rodapé com o número do processo e a tarja da
margem se repetem em toda página. Lidos em sequência com o corpo, eles
partem a frase que atravessa a página. `Chunk.furniture` marca essa linha,
sem apagá-la. Quem lê decide se a mostra, e
`Result.to_markdown(furniture=False)` devolve só o corpo.

O critério é a repetição. Uma linha é [elemento fixo](../glossary.md#elemento-fixo)
quando cumpre as duas condições abaixo:

1. Tem alguma letra, e a forma dela aparece no mesmo lugar da página em
   outra página que não é cópia desta. A forma é o texto com os dígitos e
   os algarismos romanos mascarados: `fls. 12` e `fls. 13` têm a mesma forma.
2. Está numa sequência dessas linhas a partir do alto ou do pé da página,
   ou está escrita na vertical.

Uma linha sem letra, como o número da folha, não interrompe a sequência e
não é marcada. O rótulo de um formulário no meio da página e uma lista de
números ficam sem marca.

Duas páginas são cópia uma da outra quando as linhas horizontais com letra
têm o mesmo conjunto de formas. A peça juntada duas vezes repete o corpo
inteiro no mesmo lugar, e sem essa regra a página toda seria elemento fixo.
A linha vertical da margem é julgada à parte e fica fora da comparação.

A regra é do documento inteiro. Numa leitura de uma página só, nada é
elemento fixo. Um carimbo que só uma página tem, dentro do cabeçalho,
interrompe a sequência e deixa o resto do cabeçalho dessa página sem marca.
A linha é julgada como foi lida: numa página lida de lado, a sequência
corre pelo giro da leitura.

Com o detector de layout ligado, `kind` diz o bloco em que a linha caiu.
Como os rótulos de cabeçalho e rodapé são descartados por padrão, a linha
de um cabeçalho cai no bloco vizinho. `kind` diz o bloco e `furniture` diz
a linha. Para ficar só com o corpo, use `furniture`.

`mark_furniture` é exportado para quem lê o documento em partes, com
`Document.read(pages=...)`. Ele marca os elementos fixos sobre a união das
leituras.

## Quem leu cada trecho

`Chunk.source` registra o leitor de cada trecho. Quando a cascata passa de
um leitor ao seguinte, o resultado mostra:

```python
{c.source for c in result.chunks}  # {'text_layer', 'ppocr-v5-latin'}
```

O resto da origem de cada trecho está em [Origem e cache](provenance.md).
