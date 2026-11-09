# Entregar a leitura a um agente

Este guia entrega o que a biblioteca leu a um modelo de linguagem, ou a uma
pessoa, sem perder a origem de nada. A biblioteca não decide nada com um
modelo. Ela produz o texto com a referência de cada linha, as entidades com
estado e a decisão de cada página. O modelo raciocina sobre isso e cita a
linha de onde tirou cada conclusão. Depois, a citação é conferida sem modelo.

## O que o modelo recebe

`Result.to_markdown(annotated=True)` é a forma pronta para um modelo. Cada
linha começa pela referência que o modelo cita. Ao fim de cada página vêm a
decisão da política e as entidades achadas nela.

```python
from docaudit import process
from docaudit.backends.tesseract import TesseractOCR

result = process("edital.pdf", policy="evidence", confirm=TesseractOCR())
print(result.to_markdown(annotated=True))
```

A saída abaixo é a de um edital digitalizado. O texto é o que o reconhecimento óptico de caracteres (OCR) leu, sem
a acentuação que ele perdeu (`JUDICIARIO`, `Processo no`):

```text
<!-- documento · PDF 1.4 -->
<!-- página 0 · ppocr-v5-latin -->
[p0:0] PODER JUDICIARIO DO ESTADO DE SAO PAULO
[p0:1] EDITAL DE CONVOCACAO DE INTERESSADOS
[p0:2] Processo no 1000123-47.2024.8.26.0100
[p0:3] NOME
[p0:4] CLASSE
[p0:5] VALOR
[p0:6] METALURGICA ANDRADE LTDA
[p0:7] Classe I
[p0:8] R$ 1.284.350,00
[p0:9] BANCO CREDITO NACIONAL SA ClaSse II
[p0:10] R$ 4.750.000,00
[p0:11] Requerente: JOAO DA SILVA, CPF 529.982.247-25
<!-- decisão: erro do documento: tesseract leu o mesmo -->
- CNJ: 1000123-47.2024.8.26.0100 · failed (impresso assim: tesseract) · p0:2
- valor em reais: R$ 1.284.350,00 · well_formed · p0:8
- valor em reais: R$ 4.750.000,00 · well_formed · p0:10
- CPF: 529.982.247-25 · confirmed · p0:11
```

Cada parte diz uma coisa ao modelo:

| parte | o que diz |
|---|---|
| `[p0:2]` | a página e a posição da linha na ordem de leitura deste resultado |
| `<!-- decisão: ... -->` | o que a política concluiu sobre a página |
| `failed (impresso assim: tesseract)` | o valor falha a regra, e outra família leu o mesmo: o erro está no documento |
| `failed` sem parênteses | o valor falha a regra, e o erro pode ser de leitura |
| `- linhas de lista: <referências>` | quando há, as linhas com mais de um valor do mesmo tipo, como uma fileira de tabela |
| `- blocos: <rótulo>: <referências>; ...` | quando há detector de layout, o bloco de cada linha |
| `- figura p<n>:f<i>: <fração> da página · <k> linha(s) lida(s): <referências>` | quando há, uma figura da página e as linhas lidas dentro dela |

Os estados de uma entidade estão em [Entidades padrão](entities.md).

A referência é curta de propósito. Um modelo copia `p0:2` sem errar e gasta
poucos tokens nisso. O `Chunk.id`, de 24 dígitos hexadecimais, ele copia
errado com frequência. `Result.refs()` leva da referência ao `Chunk`, e dali à
caixa, ao leitor, à confiança e ao `id`. O `id` fica para o que atravessa
execuções, como o cache e a decisão de uma revisão.

Com o leitor `vlm` sem detector de layout, a página inteira é um trecho só,
com uma referência só. Para citar a linha, dê `layout=` ao leitor ou escale
com `reread="region"`. Os detalhes estão em [Limites](limits.md).

## Poupar contexto antes do texto

Duas vistas do mesmo resultado reduzem o que vai ao modelo:

- `result.pieces()` agrupa as páginas seguidas com a mesma tarja, a faixa que
  o sistema do tribunal imprime na margem. O modelo pede o texto de uma peça,
  e não dos autos inteiros.
- `result.records()` junta as linhas em fileiras e blocos pela posição das
  caixas. `record.text` dá uma tabela com as células separadas por ` | ` e
  um parágrafo com as linhas juntas. `record.chunk_ids` leva de volta a cada
  linha, e a referência `p0:b2` cita o bloco.

```python
from docaudit import process

result = process("autos.pdf")
for piece in result.pieces():
    lines = [c for c in result.chunks if c.page in piece.pages]
    print(piece.code, piece.pages, len(lines))
for record in result.records():
    print(record.ref, record.text)
```

`to_markdown(furniture=False)` tira do texto os elementos fixos: cabeçalho,
rodapé e tarja. Nos autos, as peças de um mesmo cartório repetem no mesmo
lugar as linhas do formulário, como `Processo Digital nº`, `Classe` e
`Requerente`, e elas também saem marcadas. Para um modelo que responde quem é
a parte ou qual é o juízo, entregue o texto com os elementos fixos. A marca
fica em `Chunk.furniture`, e quem lê decide o que esconder.

## Em que ordem entregar

Entregue primeiro o contexto mais barato que responde à pergunta. É o mesmo
princípio da cascata de leitores.

| nível | o que vai ao modelo | custo | responde |
|---|---|---|---|
| 1 | as entidades e a decisão de cada página | o menor: uma linha por valor | "que CPFs há, quais falharam, em que página?" |
| 2 | o texto com referências | o do texto da página | "quem é o requerente, quanto é o total?" |
| 3 | o recorte de uma linha, em PNG (`Document.crop`) | o de uma imagem pequena | "o que está escrito nesta linha que o OCR errou?" |
| 4 | a página inteira, em PNG (`Document.render`) | o de uma imagem da página, maior que o texto dela | "o que há nesta página que o texto não mostra?" |

Três razões sustentam a ordem, além do custo:

- **O texto já foi conferido.** Uma entidade `confirmed` passou por um dígito
  verificador. Uma `failed` já foi relida por outra família, e a página diz
  se o erro é do documento. Pedir ao modelo que decida de novo, olhando a
  imagem, paga duas vezes por uma resposta pior.
- **O modelo responde melhor com menos texto.** Em perguntas sobre
  documentos, recuperar só os trechos relevantes do texto reconhecido
  responde melhor do que mandar o texto inteiro. Os autores atribuem a
  diferença à atenção diluída e à alucinação sobre texto longo
  ([ARIAL](https://arxiv.org/abs/2511.18192), seção 5.4).
- **A imagem serve para o que o texto não tem.** Um carimbo, uma assinatura,
  uma rasura, uma linha que todos os leitores erraram. É o nível 3, por
  recorte e sob demanda.

O erro de OCR também não fica onde está. Em recuperação e geração sobre
documentos, a letra trocada derruba a resposta de todos os modelos testados,
e a ordem de leitura errada derruba mais
([OHRBench](https://arxiv.org/abs/2412.02592)). Entregar as entidades com
estado é entregar o que já se sabe certo e apontar o que não está.

## Conferir a citação sem modelo

Uma citação é uma referência e o valor que o modelo diz ter lido ali. Ela
confere quando o valor está no texto da linha citada, contando só as letras e
os dígitos. Espaço, pontuação, aspas e hífen tipográfico ficam de fora: é
neles que a cópia do modelo e a leitura do OCR diferem sem mudar o que está
escrito. Um dígito trocado continua a não conferir. `Result.cited` faz a
conta e devolve as linhas, ou uma lista vazia:

```python
from docaudit import process

result = process("edital.pdf")
result.cited("p0:11", "529.982.247-25")  # [Chunk]: confere
result.cited("p0:11", "529.982.247-26")  # []: o valor não está na linha
result.cited(["p0:9", "p0:10"], "NACIONAL SA [...] R$ 4.750.000,00")  # duas linhas, com reticências
result.cited(["p0:9", "p0:10"], "R$ 4.750.000,00", entity="METALURGICA ANDRADE LTDA")  # []
```

A citação longa vem resumida com reticências. Cada pedaço tem de estar no
texto, inteiro e na ordem citada. A ordem carrega o sentido: "BETA ...
REQUERENTE" não prova o que "ALFA ... REQUERENTE" prova. `entity=` exige que
o valor da entidade, um nome ou um identificador, esteja dentro da citação, e
não só na linha. Um trecho que fala do fato sem falar da entidade não prova o
fato dela.

A referência vale dentro de um resultado. Confira contra o resultado cujo
texto o modelo leu, porque outra leitura do mesmo documento pode numerar as
linhas de outro jeito.

Descarte a citação que não confere, e deixe o campo sem valor. Um campo sem
citação válida ninguém consegue conferir na página.

## Uma extração com citação, pela API da Anthropic

O exemplo pede a um modelo os campos de um edital, cada um com a referência
da linha de onde saiu, e descarta o que não confere. O pacote `anthropic` não
é dependência da biblioteca: instale-o à parte.

```python
import anthropic
from pydantic import BaseModel

from docaudit import BBox, process
from docaudit.backends.tesseract import TesseractOCR


class Field(BaseModel):
    name: str
    value: str
    refs: list[str]


class Extraction(BaseModel):
    fields: list[Field]
    open_questions: list[str]


SYSTEM = (
    "Você lê a transcrição de um documento judicial. Cada linha começa por uma "
    "referência entre colchetes. Ao fim de cada página há a decisão da leitura e "
    "as entidades achadas, com estado: confirmed passou por dígito verificador, "
    "well_formed só tem a forma certa, failed falhou a regra. Responda só com o "
    "que está no texto, e cite em refs a referência de cada linha de onde tirou "
    "o valor. O que não está no texto vai em open_questions."
)

result = process("edital.pdf", policy="evidence", confirm=TesseractOCR())
text = result.to_markdown(annotated=True, furniture=False)

client = anthropic.Anthropic()
response = client.messages.parse(
    model="claude-opus-5-5",
    max_tokens=16000,
    system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
    messages=[
        {
            "role": "user",
            "content": (
                "Extraia: número do processo, requerente, CPF do requerente, "
                "valor total e data do edital.\n\n" + text
            ),
        }
    ],
    output_format=Extraction,
)

for field in response.parsed_output.fields:
    lines = result.cited(field.refs, field.value)
    if not lines:
        print(f"{field.name}: sem citação que confira, descartado")
        continue
    box = BBox.envelope([line.bbox for line in lines])
    print(f"{field.name}: {field.value}  (página {lines[0].page}, caixa {box.key()})")
```

O `system` é o mesmo em todo documento, e o texto muda. Por isso o `system`
vai com `cache_control`, e num lote o prefixo repetido sai do cache do
provedor. O custo da chamada está em `response.usage`, que a biblioteca não
vê: `Result.spent` conta só os leitores.

## Quando o modelo pede a imagem

O campo que ficou sem citação, ou a entidade `failed` cuja página não
explicou o erro, é o caso do nível 3. `Document` entrega o recorte da
entidade, no mesmo DPI em que os leitores a viram. Quando o valor quebra
entre duas linhas, o recorte cobre as duas.

```python
from docaudit import Document, EntityState
from docaudit.backends.tesseract import TesseractOCR

with Document("edital.pdf", confirm=TesseractOCR()) as doc:
    result = doc.read()
    for entity in result.entities:
        if entity.state is EntityState.FAILED:
            png = doc.crop(entity.page, entity.bbox)  # bytes de um PNG
            # Mande `png` ao modelo com a pergunta "que valor está escrito aqui?"
            # e confira a resposta com a mesma regra: um CPF lido na imagem só
            # vale se o dígito verificador confere.
```

A regra é a mesma da cascata. Um valor lido na imagem, por quem quer que
seja, só vale se passa na verificação do campo. O modelo é mais um leitor, e
`Check.is_valid` decide.

## Um agente que relê o que duvida

`process(confirm=...)` já relê com outra família a linha que falhou e decide
sozinho. `Document` serve quando quem decide é uma pessoa ou um agente. Ele
mantém o documento aberto, os leitores e o cache entre chamadas. Lista as
linhas cujo valor não confere, relê só o recorte com o leitor que quem decide
escolher, e entrega a imagem do recorte.

```python
from pathlib import Path

from docaudit import Document, ModelCallCache
from docaudit.backends.ppocr import PPOCR
from docaudit.backends.tesseract import TesseractOCR

cache = ModelCallCache(Path(".cache/docaudit.sqlite"))
review = Path("revisao")
review.mkdir(exist_ok=True)

with Document("autos.pdf", cheap=["text_layer", PPOCR()], cache=cache) as doc:
    result = doc.read()  # a política padrão de Document.read() é evidence
    for n, doubt in enumerate(doc.doubts(result)):
        again = doc.reread(doubt.chunk.page, doubt.chunk.bbox, TesseractOCR())
        print(doubt.chunk.page, doubt.check, doubt.value)
        print("  lido de novo:", " / ".join(c.text for c in again))
        png = doc.crop(doubt.chunk.page, doubt.chunk.bbox)
        (review / f"{n}-p{doubt.chunk.page}.png").write_bytes(png)
```

Cada `Doubt` traz a linha, o campo que falhou e o valor lido. `doubt.others`
traz as leituras de outro leitor no mesmo lugar, que dizem se o erro está
impresso no documento. Uma pessoa confere a linha lida de dois modos, com o recorte ao lado. A
resposta dela vira um rótulo para treinar o leitor; veja
[Guardar a leitura para treinar](recipes/training-pairs.md). A
assinatura de `Document` e de `Doubt` está em
[Ponto de entrada](reference/entry.md).

## Figuras: escolher as que importam e mandar no fim

Uma página nato-digital pode trazer uma planta, a foto de um bem, a tela de
um sistema, um carimbo. `result.figures()` lista essas imagens com as linhas
lidas dentro de cada uma. O texto anotado diz, ao fim da página, que a figura
existe, e o modelo sabe dela sem gastar um token de imagem.

1. Escolha as figuras pela evidência que o texto já deu: uma figura com
   linhas que trazem uma entidade do seu campo, ou numa página que o modelo
   pediu para abrir. O texto anotado conta as figuras sem texto lido numa
   linha só, porque uma digitalização fatiada em ladrilhos dá milhares de
   imagens pequenas numa página.
2. Recorte cada uma uma vez, com `Document.crop`, e grave o PNG com o nome da
   referência. O modelo recebe o arquivo no fim, sem reabrir o documento.
3. Mande ao modelo, na última chamada, só as figuras escolhidas, cada uma com
   a referência dela, e peça que cite a referência no que concluir.

```python
from pathlib import Path

from docaudit import Document

out = Path("figuras")
out.mkdir(exist_ok=True)
wanted = {"CNPJ", "RENAVAM"}
with Document("autos.pdf") as doc:
    result = doc.read()
    with_entity = {cid for e in result.entities if e.kind in wanted for cid in e.chunk_ids}
    for figure in result.figures():
        if with_entity.intersection(figure.chunk_ids):
            path = out / f"{figure.ref.replace(':', '-')}.png"
            if not path.exists():  # uma vez por figura
                path.write_bytes(doc.crop(figure.page, figure.bbox, grayscale=False))
```

O que o modelo ler na figura passa pela mesma conferência do resto. O valor
que tem regra só vale se a regra confere, e a afirmação sem referência é
descartada.

## Para uma pessoa

Tudo acima vale para uma revisão humana, com a imagem no lugar do modelo.

- `docaudit.visualize` desenha a caixa de cada linha na cor do leitor que a
  leu, e contorna em preto a linha cujo valor ainda falha.
- `Document.doubts` lista o que merece revisão: o valor que falha a
  verificação, a linha mal decodificada e, numa digitalização com camada de
  OCR, o valor em reais que a camada lê com outro número no mesmo lugar.
- As referências servem para anotar: "p0:2 está certo, é erro do documento".
  Uma ferramenta de revisão usa `Chunk.id` para prender a decisão à linha
  entre execuções, e a referência curta para a tela.
