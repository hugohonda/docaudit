# Conceitos

O que a biblioteca decide por você, e por quê: o substrato de cada página, a
cascata barata, a política, a releitura por outra família, a escalada por
região, a proveniência de cada trecho e o cache. Os argumentos
estão em [Configuração](configuration.md), e os exemplos completos em
[Receitas](recipes.md).

## Substrato

Antes de qualquer leitura, cada página é descrita por dois fatos, os dois
lidos da estrutura do PDF, sem limiar.

O substrato diz de onde veio a camada de texto:

| | Camada de texto | Confiável? |
|---|---|---|
| `BORN_DIGITAL` | à vista | sim: composta, não reconhecida |
| `SEARCHABLE_SCAN` | mais escondida que à vista | só com verificação: inserida por OCR |
| `IMAGE_ONLY` | nenhuma | n/a: OCR ou nada |

`Page.unread` diz o que nenhuma camada leu: os rasters, e o desenho vetorial,
que só um leitor de pixels lê.

```python
from docaudit.pdf import load_pages

for page in load_pages("documento.pdf"):
    print(page.index, page.substrate, page.unread, page.substrate_evidence)
```

### Por que não um booleano

A classe do meio é o ponto cego. Um `SEARCHABLE_SCAN` é um raster sobre o qual
alguém já passou OCR: o texto extrai limpo, e a página passa por nativa digital
em qualquer teste que só pergunte "tem camada de texto?". Esse texto veio de um
motor de qualidade desconhecida, e nada na aparência da página denuncia um erro
nele.

A camada é lida assim mesmo, porque é de graça, e outro OCR barato só trocaria
um erro desconhecido por outro. A classe permite à política `evidence` tratar
um CPF quebrado como leitura errada nesta página, e como erro do documento numa
página composta.

### Como as classes se separam

Mecanicamente, não estatisticamente. Um motor de OCR esconde o texto que
reconheceu, para que a página mantenha a aparência do original e ainda assim
possa ser buscada. Há duas formas de esconder, e as duas se leem do arquivo:
desenhar em modo invisível (`Tr 3`), ou desenhar à vista e cobrir com a
imagem, que vem depois no fluxo da página. Um tipógrafo desenha à vista e
não cobre.

1. Há texto embutido? Sem ele, `IMAGE_ONLY`.
2. Há mais texto escondido que à vista? Então `SEARCHABLE_SCAN`.
3. O resto é `BORN_DIGITAL`.

### O que nenhuma camada leu

Um raster foi lido quando há texto escondido dentro dele: essa camada é a
leitura que alguém já fez da imagem. Texto à vista por cima de um raster não o
lê: é o rodapé do PJe carimbado sobre a digitalização. O desenho vetorial da
página, tomado inteiro, foi lido quando há algum texto dentro dele: as linhas
de uma tabela cercam o texto das células.

Uma folha digitalizada com a tarja do e-SAJ na margem é, portanto,
`BORN_DIGITAL` com o corpo em `Page.unread`: a camada à vista é a tarja, e o
corpo é um raster que ninguém leu. A classe descreve a camada de texto, não a
folha. Quem decide o que ler é `unread`, e a cascata o lê como região.

Uma fonte embutida sem mapa para Unicode devolve o número de cada glifo no
lugar do caractere, e o texto sai como controles (U+0001, U+0003) que nenhum
texto impresso tem. O texto dessa fonte não conta como camada, e a área dele
vai em `unread`: um leitor de pixels lê o que a página mostra. Uma fonte que
mapeia um só glifo para um controle também sai inteira, porque o mapa dela
já não é confiável.

`Page.substrate_evidence` carrega os números crus (`chars`, `visible_text`,
`invisible_text`, `covered_text`, `unmapped_text`, `unread_regions`,
`native_dpi`), de modo que a decisão é auditável e reclassificável sem
reabrir o PDF.

### O que a estrutura não vê

O corpo desenhado em contornos de glifo é lido pelos pixels. O desenho sem
texto dentro vai para `Page.unread`. Com texto dentro, como uma tarja ou um
cabeçalho, vão os caminhos preenchidos com curva que nenhum texto toca,
quando são muitos: um corpo de texto tem centenas, um logotipo ou um selo
tem poucos. A régua e a moldura de uma tabela são retas, o fundo arredondado
de uma célula toca o texto dela, e os dois ficam lidos. Escapam o glifo em
contorno feito só de retas e o trecho curto em contornos, como uma linha
solta.

O número de folha desenhado antes da digitalização, e coberto por ela, não
tem esse efeito: o texto coberto só lê o raster quando é a camada da página,
isto é, quando o texto escondido supera o visível, o mesmo juízo do
substrato. Numa página de texto à vista, o texto coberto é carimbo, e o
raster segue sem leitura.

Separar esses casos pediria olhar os pixels: um detector de linhas na página
renderizada, cada linha conferida contra a camada de texto. Custa um detector
em toda página com camada de texto, e não está implementado.

## Cascata

O tier barato é uma lista ordenada de leitores, declarada pelo chamador.

```python
import docaudit
from docaudit.backends.ppocr import PPOCR

result = docaudit.process(
    "documento.pdf",
    cheap=["text_layer", PPOCR()],  # o padrão
)
```

A cascata é percorrida na ordem declarada, e a primeira leitura não vazia
vence. A camada de texto embutida é um leitor como qualquer outro, e não um
caso especial do pipeline: lê toda página com texto embutido, uma linha por
chunk, e numa página `IMAGE_ONLY` volta vazia, deixando o OCR ler.

Numa página `SEARCHABLE_SCAN` a camada veio de um OCR desconhecido, e por
padrão (`trust_layer="visible"`) não é leitura: o leitor de pixels seguinte lê
a página, e a camada entra como primeira família da releitura, antes de
`confirm`, sem custo. A linha da camada com um id que confere (CPF, CNPJ,
número CNJ, uma verificação com redundância) e que os pixels não
confirmaram entra no resultado, com `source` `text_layer`, no lugar das
linhas dos pixels no mesmo lugar da folha; cada linha trocada fica em
`Result.others` com `replaced`. A tarja e o carimbo de folha que o tribunal
desenha à vista por cima da digitalização são texto exato, e entram do mesmo
jeito. Uma camada que discorda dos pixels sem
deixar valor impossível nenhum sinal pega.
`trust_layer="always"` lê a camada como está.

Um leitor que devolve texto sem ter pedido os pixels, que é o caso da camada de
texto, deixa sem ler o que está em `Page.unread`. O leitor seguinte da
cascata lê o recorte de cada raster com a folga de `RASTER_MARGIN` (0,15 da
folha), e ficam as linhas cujo centro cai no raster e não cai em nada já
lido: o rodapé carimbado já veio da camada. A folga, porque o recorte justo
corta o texto na borda e o detector de linhas parte a linha ali; a partir de
0,15 a leitura é a da página inteira. `Result.spent.regions_cheap`
conta as páginas lidas assim.

Cada linha lida assim diz em `Chunk.region` o índice do raster em
`Page.unread`, e entra na ordem de leitura no lugar do raster: antes da
primeira linha da camada cujo topo fica abaixo do topo do raster. A
digitalização inteira com o rodapé carimbado por cima fica com o corpo antes
do rodapé; a figura no meio de uma página composta fica entre o texto de
cima e o de baixo. `Page.unread` vem de cima para baixo e da esquerda para a
direita, qualquer que seja a ordem dos objetos no fluxo da página.

## Os elementos fixos da página

O cabeçalho do tribunal, o rodapé com o número do processo e a tarja da
margem repetem-se em toda página, e lidos em sequência com o corpo partem a
frase que atravessa a folha. `Chunk.furniture` marca essa linha, sem a
apagar: quem lê decide se a mostra, e `Result.to_markdown(furniture=False)`
devolve só o corpo.

A regra é a repetição, não um modelo: uma linha com alguma letra cuja forma,
com os dígitos e os romanos mascarados, aparece no mesmo lugar da folha em
outra página, e que está numa sequência dessas linhas a partir do alto ou do
pé da página, ou escrita na vertical. O número
da folha, sem letra, não interrompe a sequência e não é marcado. O rótulo de
um formulário no meio da página e uma lista de números não são marcados. A
regra é do documento inteiro: numa leitura de uma página só nada é elemento fixo,
e um carimbo de uma página só dentro do cabeçalho deixa o resto do cabeçalho
dessa página sem marca. Um detector de layout, quando ligado, dá em
`kind` o bloco em que a linha caiu, e com os rótulos de cabeçalho e rodapé
descartados por padrão a linha de um cabeçalho cai no bloco vizinho:
`kind` diz o bloco, `furniture` diz a linha, e para ficar só com o corpo
vale `furniture`. `mark_furniture` é exportado para quem lê o documento em
partes, com `Document.read(pages=...)`, e quer a marca sobre a união das
leituras.

A linha é a que o pdfium monta. Um gerador que posiciona cada letra
isoladamente produz um retângulo por letra, e ler retângulos faria "Banco" virar
cinco chunks.

`Chunk.source` registra qual leitor leu cada trecho, de modo que um fallback
nunca é silencioso:

```python
{c.source for c in result.chunks}  # {'text_layer', 'ppocr-v5-latin'}
```

Reordenar, encurtar ou trocar a cascata é argumento de chamada, não alteração de
código.

## Política

A política decide o tier de cada página. As embutidas, pelo nome, são
`all_cheap` (só a leitura barata), `all_strong` (tudo com o leitor caro) e
`evidence`. A linha de base ao acaso, sem a qual o ganho de uma cascata não se
interpreta, é calculada por quem avalia, e não por uma política. O
exemplo de chamada está em [Começando](getting-started.md).

`Budget` é um teto opcional, em páginas, de quantas chegam ao leitor caro numa
chamada; os detalhes estão em [Configuração](configuration.md#orcamento).
Tempo, tokens e dólares são relatados, não limitados.

### Decidir antes ou depois da leitura barata

Uma política declara `needs_reads`. Com `False`, ela decide só pelo substrato,
antes de qualquer leitura, e uma página escalada nunca paga o tier barato. É o
caso de `all_cheap` e `all_strong`.

Com `True`, `process()` lê toda página no tier barato, passa as leituras em
`decide(pages, budget, reads)`, e a leitura cara substitui a barata nas páginas
escaladas, só onde a cara leu: um leitor por região descarta cabeçalho, rodapé
e a tarja da margem, e essas linhas ficam da leitura barata. Uma página
escalada é lida duas vezes. É o caso de `evidence`.

### A política `evidence`

Escala só a página cuja leitura barata provou ter falhado, e o motivo fica em
`RoutingDecision.reason`. Cada sinal diz quantas ocorrências encontrou; a
prioridade é a ordem da lista de sinais, e dentro de um sinal, mais
ocorrências primeiro. Os padrões são categóricos, sem limiar ajustado:

| sinal | por quê |
|---|---|
| `EmptyRead()` | nada foi lido |
| `GarbledText()` | caracteres que só uma decodificação quebrada produz: o de substituição, os da área de uso privado, que saem de uma fonte sem tabela ToUnicode, e os de controle. Vale também em texto composto, porque reler os pixels conserta o que a decodificação quebrou |
| `FailsCheck(CPF)`, `FailsCheck(CNPJ)`, `FailsCheck(CNJ)` | id na pontuação canônica com dígito verificador errado; vírgula no lugar de ponto casa. Só um documento imprimindo um id produz essa forma. O CNPJ pode ser alfanumérico |
| `FailsCheck(AMOUNT_BRL)` | valor que a grafia brasileira não permite: duas vírgulas, espaço entre grupos de milhar, letra no lugar de dígito, grupo sem três dígitos |
| `FailsCheck(AMOUNT_PRE_REAL)` | o mesmo, no valor em cruzeiro, cruzado ou cruzeiro real (`Cr$`, `NCr$`, `Cz$`, `NCz$`, `CR$`) |

Cada `FailsCheck` recebe um `Check`: o nome do campo, a forma impressa e uma
função que diz se o valor é possível. O sinal conta as ocorrências que falham,
e a decisão cita o campo: `1 x CPF que falha a verificação`.

`EvidenceRouter(min_failures=n)` só escala por verificação a página com pelo
menos `n` valores que falham, somados entre os `FailsCheck`. Reler a página
inteira conserta onde a leitura barata errou em série, como numa lista densa
digitalizada em baixa resolução. Na página com um valor errado, a releitura
custa a página toda e quase nunca traz o valor. A leitura vazia e o texto mal
decodificado escalam com uma ocorrência. O padrão é 1, que escala toda falha.
O mínimo não é calibrado. Vale
também com `reread="region"`, em que o recorte de uma linha já é barato, e
ali o mínimo corta essa releitura.
A página que fica barata guarda o valor que falha em `signals` e nas
entidades, e `reason` diz que ficou abaixo do mínimo.

O campo só conta em texto escrito por máquina: a camada de uma página
`SEARCHABLE_SCAN`, e o que um leitor de pixels leu em qualquer página. Na
camada à vista o erro é do documento, e reler devolveria o mesmo erro. Os
falsos positivos conhecidos são dois. Uma folha em branco volta vazia. E um
documento que imprime um id ou uma data errados dispara, e reler devolve o
mesmo valor.

A data que não existe no calendário e a palavra que mistura dois alfabetos
ficam fora dos sinais padrão. Um piso de confiança também fica fora: a escala muda de um motor
para outro, e um piso seria um número sem medição.

Sem evidência a política não escala nada. Quando um teto não cobre todas as
páginas com evidência, a ordem é a da lista, e essa ordem não foi medida.

### Reler com outra família antes de pagar

`process(..., confirm=TesseractOCR())` relê, com um leitor de outra família,
a página que uma verificação encaminhou, antes do leitor caro. Numa página
`SEARCHABLE_SCAN` a primeira família é a própria camada de OCR embutida, que
já está lida; `confirm` vem depois, e a primeira que decide encerra. Duas famílias
que devolvem o mesmo valor inválido confirmam que o erro está impresso no
documento: a página fica em `CHEAP`, com o motivo "erro do documento". Se a
releitura traz, no mesmo lugar de cada valor inválido, um valor que confere,
essas linhas trocam e a página também fica em `CHEAP`, com o motivo
"corrigido por". Nos outros casos a página segue ao leitor caro. "Vale o
valor válido" seria a regra errada: uma leitura errada pode conferir, e por
isso a troca exige a mesma posição e nenhum valor inválido restante. A página
encaminhada por leitura vazia ou texto mal decodificado não passa por aqui.
O Tesseract relê a página inteira: numa lista densa, custa mais que um PP-OCR
maior como leitor caro. `confirm` vale quando o leitor caro é bem mais caro,
como um modelo de visão e linguagem, ou quando importa separar o erro impresso
no documento do erro de leitura.
`Result.spent` conta `pages_confirmed`, `pages_confirmed_same`,
`pages_confirmed_fixed` e `seconds_confirm`.

### Reler a região, não a página

Uma verificação diz em que linha a leitura falhou: `FailsCheck.failing`
devolve cada valor inválido com o chunk em que está. Com
`process(..., reread="region")`, o leitor caro recebe só a menor caixa que
contém essas linhas, e substitui só o que leu ali. O resto da página fica da
leitura barata. É a diferença entre pagar uma folha e pagar um recorte.

A página vai inteira, nos dois modos, quando disparou nela um sinal que não
aponta linha: leitura vazia, texto mal decodificado ou um sinal próprio. Um
recorte ali deixaria o resto da falha na página. O padrão é `"page"`.
`Result.spent.regions_strong` conta as páginas em que o leitor caro leu só
a região. O recorte entra no cache com a caixa na chave: uma caixa diferente
é uma leitura diferente.

### A leitura cara passa pelas mesmas verificações

A leitura cara substitui a barata só onde leu, e só onde não perde nada
que a barata tinha certo. Uma linha cara que cobre uma linha barata com um
CPF, CNPJ, número CNJ ou valor que confere, e não traz esse valor, é
recusada: fica a linha barata. O número com vírgula decimal e milhar no
lugar conta como valor mesmo sem o `R$`, porque numa tabela o símbolo fica no
cabeçalho; a linha cara que lê `15.062.39` onde a barata leu `15.062,39` é
recusada. Para o valor que falhou e motivou a escalada,
vale o mesmo veredito da releitura por outra família: a linha cara no mesmo
lugar com o valor que confere conserta; a que traz o mesmo valor inválido
não conserta, e a barata fica; a que traz outra coisa não explicou nada, e a
barata fica. O leitor caro não é declarado de outra família, e a repetição
dele não marca `Entity.printed`: só `confirm` e a camada oculta provam o erro
do documento. `Result.spent.lines_strong_rejected` conta
as recusas, e `steps` diz o porquê de cada uma. O que isso evita: o PaddleOCR-VL
na página inteira, em 108 páginas, perdia 26 de 106 números CNJ e 92 de 380
valores que o primeiro nível leu certo.

### Sinais e verificações próprios

A lista de sinais é sua. Um sinal é uma função `(page, chunks) -> int`; uma
verificação é um campo com forma impressa e regra de validade. Os dois entram
na lista que `EvidenceRouter` recebe, e a posição é a prioridade. Ver
[Configuração](configuration.md#uma-verificacao-propria).

A mesma verificação produz `Result.entities`: cada valor que ela casa, em
qualquer linha, com o estado `confirmed`, `well_formed` ou `failed` e as
linhas de origem. Uma verificação na política encaminha e extrai; uma em
`entities=` só extrai. Ver [Entidades](entities.md).

### Ordem de leitura por layout

Um OCR por linha devolve as linhas pela altura na página. Numa folha em duas
colunas, um diário oficial ou um acórdão, isso intercala as colunas: a linha
de um valor é seguida pela linha de um endereço da outra coluna, e quem lê o
texto, pessoa ou modelo, perde o fio. A camada de texto de um PDF vem na
ordem em que foi gravada, e há arquivos em que ela começa pelo rodapé.

`process(..., layout=PPDocLayout(drop=()))` resolve isso com o detector de
layout que o leitor `VLM` já usa. Depois de todas as leituras, cada linha vai
ao bloco que contém o seu centro, ou ao mais próximo; os blocos saem na ordem
do detector e as linhas de cima para baixo dentro de cada um. A linha ganha
o rótulo do bloco em `kind` quando o leitor não deu um. Vale para a linha
barata, para a que o leitor caro pôs no lugar e para a camada de texto. Sem
bloco nenhum na página, a ordem de cada leitor fica como veio. O porquê de
`drop=()` está em [Configuração](configuration.md#ppdoclayout). Custa uma
detecção por página ([Desempenho](performance.md#leitores)), e entra nos
segundos da etapa em que a página foi renderizada.

### O que aconteceu com cada página

`RoutingDecision.steps` conta, uma frase por passo e na ordem, o que `process`
fez com a página: quem leu no tier barato e quantas linhas, o que a política
decidiu, o que a releitura por outra família concluiu, o que o leitor caro leu
e quantas linhas substituiu. `visualize` desenha, na imagem de cada página,
a caixa de cada linha na cor do leitor que a leu.

### O que custou

`Result.spent` relata o gasto de cada chamada, sem o que o cache poupou. As
chaves estão em [Formato da resposta](response.md#spent).

## Proveniência

Cada `Chunk` carrega página, caixa, leitor e ordem de leitura.

```python
for c in result.chunks:
    px = c.bbox.to_pixels(1653, 2339)
    print(c.page, px, c.source, c.confidence, c.reading_order, c.text[:50])
```

**O texto como lido.** `Chunk.text` é o que o leitor devolveu, sem correção.
A camada de texto sai em NFC, e as verificações procuram a forma impressa num
texto com hífens, espaços e formas de largura total tipográficos trocados pelo
ASCII, sem mudar a posição de nenhum caractere.

**Caixas normalizadas.** O formato está em
[Formato da resposta](response.md#a-caixa). A caixa não guarda pixels: uma caixa em pixels só significa
alguma coisa junto do DPI em que a página foi renderizada, e esse par se separa
na primeira serialização. `to_pixels()` e `from_pixels()` convertem na borda,
onde o DPI ainda está à mão.

**Ids endereçados por conteúdo.** O id de um trecho é determinístico: o mesmo
documento, com os mesmos leitores, gera os mesmos ids, com ou sem cache e em
qualquer máquina. Entram o hash do documento, o DPI, o índice da página, a
caixa, o leitor e o texto. O texto entra inteiro porque dois chunks podem
ocupar a mesma caixa no mesmo motor, como uma célula e a linha que a contém,
e o índice da página entra porque um documento pode ter duas páginas de bytes
idênticos. Nenhum pixel entra: o documento e o DPI já determinam a
renderização.

**A execução.** `Result.run` diz com que política, leitores e argumentos o
resultado saiu, e em `versions` a versão de cada leitor que leu uma linha:
pesos, motor, dispositivo, idioma, prompt. O `source` de um trecho é a
chave. A versão fica ao lado do id, e não dentro dele, para que a citação
de uma linha sobreviva a uma troca de pesos que não mudou a leitura. Com
o PDF e o `Result` em JSON guardados, a leitura se refaz, e qualquer
recorte sai de novo de `Document.crop`: ver
[Receitas](recipes.md#guardar-a-leitura-para-treinar-depois).

**A leitura que saiu.** Quando a releitura por outra família ou o leitor
caro substitui uma linha por outro texto, a linha que saiu fica em
`Result.others`, com `replaced`, ao lado da que entrou. A releitura
recusada no lugar de uma linha que falha também fica ali, ao lado da linha
que continuou. Duas coisas saem sem rastro. A linha mal decodificada fora
das caixas do leitor caro é lixo por definição. A linha cara recusada longe
de um valor que falhou aparece em `steps` e em `spent.lines_strong_rejected`.

**O que o arquivo diz de si.** `Result.document` traz o produtor, as datas,
a versão, as assinaturas declaradas e quantas vezes o arquivo foi gravado;
`Page.hidden_fonts` traz as fontes da camada invisível de cada página. Esses
campos provam menos do que parecem, e vale saber o quê. O `producer` é de
quem gravou o arquivo por último, não de quem o criou: um PDF dividido em
páginas por uma ferramenta de tribunal ou de raspagem sai com o nome dessa
ferramenta, sem assinatura, muitas vezes sem data e sem `/ID`. `saves` e
`identifier_changed` são o rastro dessa regravação. As fontes da camada
invisível sobrevivem à divisão, e são o que diz qual motor escreveu a
camada de uma digitalização, sem a biblioteca nomear motor nenhum: o
Tesseract deixa `GlyphLessFont`, um montador as fontes base do PDF. Uma
assinatura é lida como o arquivo a declara, sem conferir a criptografia.
O que esses campos dizem com segurança é o oposto: um documento inteiro,
assinado e com `saves` igual a um, chegou como saiu de quem o emitiu.

## Cache

`ModelCallCache` guarda a leitura de cada página por cada leitor, nos dois
tiers.

```python
from pathlib import Path
from docaudit import ModelCallCache

cache = ModelCallCache(Path(".cache/docaudit.sqlite"))
result = docaudit.process("documento.pdf", cache=cache)
```

Vários processos podem partilhar o mesmo arquivo de cache.

A chave tem estes componentes, cada um por um motivo:

| componente | por quê |
|---|---|
| hash do documento, índice da página, DPI | a entrada: juntos determinam os pixels |
| a caixa da região, quando o leitor lê uma | uma região da página é outra leitura |
| nome do leitor | quem leu |
| `output_version` do leitor | pesos, idioma, prompt e formato do que ele produz |
| digest do esquema de `Chunk` | que forma tem o que está guardado |

Nenhum pixel entra na chave: consultar o cache não custa renderizar, e a camada
de texto continua sem renderizar. Duas páginas de bytes idênticos não partilham
a entrada.

Versão e digest existem contra a falha silenciosa. Sem eles, uma entrada
gravada num formato continua sendo lida depois de o formato mudar, e o
Pydantic preenche o que falta por omissão. O digest sai dos campos do próprio
`Chunk`, e por isso muda sem que alguém precise lembrar de incrementá-lo.

## Dados que saem da máquina

Um leitor que envia dados para fora é recusado sem `allow_external=True`. Ver
[Segurança dos dados](security.md).
