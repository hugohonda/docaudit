# Substrato

Antes de qualquer leitura, a biblioteca descreve cada página por dois fatos.
Os dois saem da estrutura do PDF, sem renderizar a página e sem limiar.

- O [substrato](../glossary.md#substrato) diz de onde veio a camada de texto.
- `Page.unread` diz o que nenhuma camada de texto leu: o
  [raster não lido](../glossary.md#raster-nao-lido).

| substrato | camada de texto | o que ela vale |
|---|---|---|
| `BORN_DIGITAL` | à vista | é o texto que o programa compôs; um erro nela está no documento |
| `SEARCHABLE_SCAN` | mais texto escondido que à vista | veio de um motor de OCR (reconhecimento óptico de caracteres) desconhecido; vale só conferida |
| `IMAGE_ONLY` | nenhuma | não há camada; só um leitor de pixels lê a página |

```python
from docaudit.pdf import load_pages

for page in load_pages("documento.pdf"):
    print(page.index, page.substrate, page.unread, page.substrate_evidence)
```

## A classe do meio

Uma página `SEARCHABLE_SCAN` é uma digitalização sobre a qual alguém já
passou OCR. O texto extrai limpo.
Um teste que só pergunta "a página tem camada de texto?" a toma por
nato-digital. Esse texto, porém, veio de um motor de qualidade
desconhecida, e nada na aparência da página mostra um erro nele.

Por isso a classe muda duas coisas adiante:

- Por padrão, a camada dessa página não é a leitura. Um leitor de pixels lê
  a página, e a camada entra depois como primeira
  [família](../glossary.md#familia) da releitura. Ver
  [Cascata](cascade.md#a-camada-de-uma-digitalizacao-com-ocr).
- Uma verificação que falha muda de sentido. Nessa página, um CPF com
  dígito verificador errado é leitura errada. Numa página nato-digital, é
  erro do documento, e reler devolveria o mesmo valor. Ver
  [Política](policy.md#a-politica-evidence).

## Como as classes se separam

Um motor de OCR esconde o texto que reconheceu. Assim a página mantém a
aparência do original e ainda aceita busca. Há duas formas de esconder, e
as duas se leem do arquivo:

- desenhar o texto em modo invisível, o operador `Tr 3` do PDF;
- desenhar o texto à vista e cobri-lo com a imagem, que vem depois no
  fluxo da página.

O programa que compõe um documento desenha o texto à vista e não o cobre.
A decisão segue três perguntas, nesta ordem:

1. A página tem texto embutido? Sem ele, é `IMAGE_ONLY`.
2. Há mais texto escondido que à vista? Então é `SEARCHABLE_SCAN`.
3. O resto é `BORN_DIGITAL`.

A contagem é por objeto de texto do PDF. Nenhum dos testes tem limiar: um
objeto foi desenhado sem tinta, foi coberto por uma imagem, ou nenhum dos
dois.

## O que nenhuma camada leu

`Page.unread` lista as caixas que nenhuma camada de texto leu. São três
tipos de coisa: rasters, desenho vetorial e texto numa fonte sem mapa.

- **Raster.** Um raster foi lido quando há texto escondido dentro dele:
  essa camada é a leitura que alguém já fez da imagem. Texto à vista por
  cima de um raster não o lê. É o rodapé do PJe carimbado sobre a
  digitalização, ou a legenda de uma foto. Os rasters que se tocam, como os
  ladrilhos de uma digitalização fatiada, contam como uma imagem só.
- **Desenho vetorial.** O desenho da página, tomado inteiro, foi lido
  quando há algum texto dentro dele. As linhas de uma tabela cercam o texto
  das células.
- **Fonte sem mapa.** Uma fonte embutida sem mapa para Unicode devolve o
  número de cada glifo no lugar do caractere. O texto sai como caracteres
  de controle, U+0001 ou U+0003, que nenhum texto impresso tem. O texto
  dessa fonte não conta como camada, e a área dele vai para `unread`. Basta
  um glifo virar controle para a fonte inteira sair, porque o mapa dela
  deixou de ser confiável.

A classe descreve a camada de texto, e não a página. Uma página
digitalizada com a [tarja](../glossary.md#tarja) do e-SAJ na margem é
`BORN_DIGITAL`: a camada à vista é a tarja. O corpo é um raster que ninguém
leu, e fica em `Page.unread`. É `unread` que decide o que ler, e a cascata
lê esse raster como um recorte. Ver
[Cascata](cascade.md#rasters-que-a-camada-nao-leu).

`Page.unread` vem ordenada de cima para baixo e da esquerda para a direita,
qualquer que seja a ordem dos objetos no fluxo da página.

`Page.substrate_evidence` guarda os números crus da decisão: `chars`,
`visible_text`, `invisible_text`, `covered_text`, `unmapped_text`,
`unread_regions` e, quando há raster, `native_dpi`. Com eles, a decisão pode ser auditada e
refeita sem reabrir o PDF.

## O que a estrutura não vê

Alguns geradores desenham o corpo do texto em contornos de glifo, sem
objeto de texto nenhum. Esse corpo só se lê pelos pixels. Sem texto no
desenho, ele já vai inteiro para `unread`.

Com texto no desenho, como uma tarja ou um cabeçalho, a biblioteca procura
os caminhos preenchidos e com curva que nenhum texto toca. Quando há pelo
menos `MIN_OUTLINES` deles, a caixa que os envolve vai para `unread`. Um
corpo de texto tem muitos desses caminhos; um logotipo ou um selo tem
poucos. `MIN_OUTLINES` é um parâmetro nomeado, sem calibração.

A régua e a moldura de uma tabela são retas, e o fundo arredondado de uma
célula toca o texto dela. Os dois contam como lidos. Escapam dois casos: o
glifo em contorno feito só de retas, e o trecho curto em contornos, como
uma linha solta.

O texto coberto por uma imagem só lê o raster quando é a camada da página.
Isso acontece quando o texto escondido supera o visível. É o mesmo critério do
substrato. Numa página de texto à vista, o texto coberto é um carimbo, como
o número de folha desenhado antes da digitalização, e o raster continua sem
leitura.

Separar esses casos pediria olhar os pixels: uma detecção de texto na
página renderizada, com cada linha conferida contra a camada de texto. Isso
custaria uma detecção em toda página com camada de texto, e não está
implementado.
