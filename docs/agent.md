# Análise por um agente

Como entregar o que a biblioteca leu a um modelo de linguagem, ou a uma
pessoa, sem perder a origem de nada. A biblioteca não decide nada com um
modelo: ela produz o texto com a linha de cada trecho, as entidades com
estado, e a decisão de cada página. O modelo raciocina sobre isso, cita a
linha de onde tirou cada conclusão, e a citação é conferida sem modelo.
Esta página diz o que entregar, em que ordem, e por quê.

## O que o modelo recebe

`Result.to_markdown(annotated=True)` é a forma pronta para um
modelo: uma linha por trecho, cada uma começando pela referência que o
modelo cita, e ao fim de cada página a decisão da cascata e as entidades
achadas nela. Um `failed` com `(impresso assim: <quem>)` é erro do
documento, e `<quem>` é a prova ([Entidades](entities.md)). Sem os
parênteses, o erro pode ser de leitura.

```text
<!-- página 3 · ppocr-v5-latin -->
[p3:0] PODER JUDICIARIO DO ESTADO DE SAO PAULO
[p3:1] Processo no 9001087-60.2022.8.26.0390
[p3:2] Requerente: JOAO DA SILVA, CPF 529.982.247-26
[p3:3] Total: R$
[p3:4] 4.000,00 (quatro mil reais)
<!-- decisão: erro do documento: tesseract leu o mesmo -->
- CNJ: 9001087-60.2022.8.26.0390 · confirmed · p3:1
- CPF: 529.982.247-26 · failed (impresso assim: tesseract) · p3:2
- valor em reais: R$ 4.000,00 · well_formed · p3:3, p3:4
```

A referência `p3:2` é a página e a posição da linha na ordem de leitura
deste resultado. `Result.refs()` devolve o dicionário de referência para
`Chunk`, e por ele o caminho de volta: a caixa, o leitor, a confiança, o
`id` estável. A referência é curta de propósito: um modelo copia `p3:2`
sem errar e gasta poucos tokens nisso; um `id` de 24 dígitos hexadecimais
ele copia errado com frequência, e numa página de quarenta linhas custa mais
que o texto. O `id` fica para o que atravessa execuções, como o cache e uma
decisão de revisão.

Com o leitor `vlm` sem detector, a página inteira é um trecho com uma
referência só ([Limites](limits.md)). Para citar a linha, dê `layout=` ao
leitor ou escale com `reread="region"`.

Ao fim de cada página, `linhas de lista` diz quais linhas trazem mais de um
valor do mesmo tipo, como uma fileira de tabela com dois CNPJ ou dois
valores; com um detector de layout, `blocos` diz em que bloco cada linha
caiu. É o que diz ao modelo se um trecho é uma fileira de tabela, que se lê
célula a célula, ou uma frase.

Duas vistas do mesmo resultado poupam contexto antes do texto.
`result.pieces()` agrupa as páginas seguidas com a mesma tarja: um modelo
pede o texto de uma peça, `[c for c in result.chunks if c.page in piece.pages]`,
em vez do auto inteiro. `result.records()` junta as linhas em fileiras e
blocos só pela posição das caixas: `record.text` dá uma tabela com as
células separadas por ` | ` e um parágrafo com as linhas juntas, em menos
trechos que a lista de linhas; `record.chunk_ids` leva de volta a cada
linha, e a referência `p3:b2` cita o bloco ([Formato da resposta](response.md#record)).

`furniture=False` tira do texto o cabeçalho, o rodapé e a tarja. Num auto,
as peças de um mesmo cartório repetem no mesmo lugar as linhas do
formulário, `Processo Digital nº`, `Classe`, `Requerente`, `Juiz(a) de
Direito`, e elas saem marcadas também. Para um modelo que responde quem é a
parte ou qual é o juízo, entregue o texto com os elementos fixos: a marca
fica em `Chunk.furniture`, e quem lê decide o que esconder.

## Em que ordem entregar

O princípio é o mesmo da cascata de leitores: o contexto mais barato que
responde à pergunta. Há quatro níveis: a lista de entidades custa uma
fração do texto, e a imagem de duas vezes e meia a quatro vezes o texto.

| nível | o que vai ao modelo | custa | responde |
|---|---|---|---|
| 1 | as entidades e a decisão de cada página | dezenas de tokens por página | "que CPFs há, quais falharam, em que página?" |
| 2 | o texto com referências | centenas de tokens por página | "quem é o requerente, quanto é o total?" |
| 3 | o recorte de uma linha, em PNG (`Document.crop`) | milhares de tokens por recorte | "o que está escrito nesta linha que o OCR errou?" |
| 4 | a página inteira, em PNG (`Document.render`) | milhares de tokens por página | "o que há nesta página que o texto não mostra?" |

Três coisas justificam a ordem, além do custo:

- **o texto já foi conferido.** Uma entidade `confirmed` passou por um
  dígito verificador; com `confirm=`, uma `failed` já foi relida por outra
  família, e `Entity.printed` diz se o erro é do documento. Mandar a imagem para o modelo decidir
  de novo o que a regra já decidiu é pagar duas vezes pela resposta pior;
- **o modelo lê melhor menos texto.** Em avaliação de perguntas sobre
  documentos, recuperar só os trechos relevantes do texto reconhecido
  responde melhor do que mandar o texto inteiro, e os autores atribuem a
  diferença à atenção diluída e à alucinação sobre texto longo
  ([ARIAL](https://arxiv.org/abs/2511.18192), seção 5.4);
- **a imagem é para o que o texto não tem.** Um carimbo, uma assinatura, uma
  rasura, uma linha que todos os leitores erraram. É o nível 3, por recorte
  e sob demanda, que `Document` serve sem reler o documento.

Há um quarto motivo para não mandar texto não conferido: o erro de OCR não
fica onde está. Em recuperação e geração sobre documentos, o ruído
semântico, a letra trocada, derruba a resposta de todo modelo testado, e
derruba mais a ordem de leitura; o ruído de formato os modelos maiores
toleram ([OHRBench](https://arxiv.org/abs/2412.02592)). Entregar as
entidades com estado, em vez do texto cru, é entregar ao modelo o que já se
sabe que está certo e apontar o que não está.

O que não fazer: mandar todas as páginas em imagem para um modelo e pedir
que ele extraia tudo. Custa o nível 4 em toda página, e o modelo perde
valores que o primeiro nível tinha certo: ver
[Conceitos](concepts.md#a-leitura-cara-passa-pelas-mesmas-verificacoes) e a nota de leitores.

## Conferir a citação sem modelo

Uma citação é uma referência e o valor que o modelo diz ter lido ali. Ela
confere quando o valor está no texto da linha citada, contando só as letras
e os dígitos: espaço, pontuação, aspas e hífen tipográfico ficam de fora,
porque é neles que a cópia do modelo e a leitura do OCR diferem sem mudar o
que está escrito; um dígito trocado continua a não conferir. Nenhum modelo
entra nessa conferência, e por isso ela não alucina. `Result.cited` faz a
conta e devolve as linhas, ou nada:

```python
result.cited("p3:2", "529.982.247-26")  # [Chunk]: confere
result.cited("p3:2", "529.982.247-25")  # []: o valor não está na linha
result.cited(["p3:3", "p3:4"], "R$ 4.000,00")  # o valor que quebra entre duas linhas
result.cited("p7:4", "ALFA LTDA [...] REQUERENTE")  # a citação longa, resumida com reticências
result.cited("p7:4", "na condição de REQUERENTE", entity="ALFA LTDA")  # []: a entidade não está na citação
```

Uma citação longa vem resumida com reticências. Cada pedaço tem de estar no
texto, inteiro e na ordem citada: a ordem carrega o sentido, e "BETA ...
REQUERENTE" não prova o que "ALFA ... REQUERENTE" prova. `entity=` exige que o
valor da entidade (o nome, o id) esteja dentro da citação, não só na linha:
um trecho que fala do fato sem falar da entidade não prova o fato dela. É a
porta que separa "o trecho existe" de "o trecho diz isto desta pessoa".

A referência vale
dentro de um resultado: confira contra o resultado cujo texto o modelo leu,
porque outra leitura do mesmo documento pode numerar as linhas de outro jeito.

Uma citação que não confere é descartada, e o campo fica sem valor. Isto
vale mais que a confiança do modelo: um campo sem citação válida é um campo
que ninguém pode conferir na folha.

## Uma extração com citação, pela API da Anthropic

O exemplo abaixo pede a um modelo os campos de um edital, cada
um com a referência da linha de onde saiu, e descarta o que não confere. O
pacote `anthropic` não é dependência da biblioteca; instale-o à parte.

```python
import anthropic
from pydantic import BaseModel

import docaudit
from docaudit import BBox
from docaudit.backends.tesseract import TesseractOCR


class Field(BaseModel):
    name: str
    value: str
    refs: list[str]


class Extraction(BaseModel):
    fields: list[Field]
    open_questions: list[str]


result = docaudit.process("edital.pdf", policy="evidence", confirm=TesseractOCR())
text = result.to_markdown(annotated=True, furniture=False)

client = anthropic.Anthropic()
response = client.messages.parse(
    model="claude-opus-5-5",
    max_tokens=16000,
    system=(
        "Você lê a transcrição de um documento judicial. Cada linha começa por uma "
        "referência entre colchetes. Ao fim de cada página há a decisão da leitura e "
        "as entidades achadas, com estado: confirmed passou por dígito verificador, "
        "well_formed só tem a forma certa, failed falhou a regra. Responda só com o "
        "que está no texto, e cite em refs a referência de cada linha de onde tirou "
        "o valor. O que não está no texto vai em open_questions."
    ),
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

O `system` é estável e o documento muda: num lote, o `system` vai com
`cache_control` e o texto de cada documento vem depois, para que o
prefixo repetido custe uma fração. O modelo é o argumento `model`, e o
custo por documento é o de `response.usage`, que a biblioteca não vê:
`Result.spent` conta só os leitores.

## Quando o modelo pede a imagem

O campo que ficou sem citação, ou a entidade `failed` cuja página não
explicou o erro, é o caso do nível 3. `Document` entrega o recorte da
entidade, as duas linhas quando o valor quebra entre elas, no mesmo DPI em
que os leitores a viram, e o modelo responde olhando só para ele:

```python
from docaudit import Document, EntityState

with Document("edital.pdf", confirm=TesseractOCR()) as doc:
    result = doc.read()
    for entity in result.entities:
        if entity.state is EntityState.FAILED:
            png = doc.crop(entity.page, entity.bbox)  # bytes de um PNG
            # mande `png` ao modelo com a pergunta "que valor está escrito aqui?",
            # e confira a resposta com a mesma regra: um CPF que o modelo leu
            # na imagem só vale se o dígito verificador confere.
```

A regra de conferência é a mesma da cascata: um valor lido na imagem, por
quem quer que seja, só vale se passa na verificação do campo. O modelo é
mais um leitor, e `Check.is_valid` é quem decide.

## Figuras: guardar as que importam e mandar no fim

Uma página composta pode trazer uma planta, a foto de um bem, a tela de um
sistema, um carimbo. `result.figures()` lista essas imagens com as linhas
lidas dentro de cada uma, e o texto anotado diz, ao fim da página, que a
figura existe: `- figura p466:f0: 34% da página · 12 linha(s) lida(s)`. O
modelo sabe que ela está ali sem gastar um token de imagem.

A ordem é a mesma das outras entregas: primeiro o que custa menos.

1. Escolha as figuras pela evidência que o texto já deu: uma figura com
   linhas que trazem uma entidade do seu campo, ou numa página que o modelo
   escolheu abrir. Numa página com um termo do seu domínio, a maior figura
   sem texto lido costuma ser a que importa. O texto anotado conta as figuras
   sem texto numa linha só, porque uma digitalização fatiada em ladrilhos
   dá milhares de imagens pequenas numa página.
2. Recorte cada uma uma vez, com `Document.crop`, e grave o PNG com o nome
   da referência. Renderizar custa milissegundos; o que se guarda é o
   arquivo, para que o modelo o receba no fim sem reabrir o documento.
3. Mande ao modelo, na última chamada, só as figuras escolhidas, cada uma
   com a referência dela, e peça que cite a referência no que concluir.

```python
from pathlib import Path

from docaudit import Document

out = Path("figuras")
out.mkdir(exist_ok=True)
wanted = {"CNPJ", "RENAVAM"}
with Document("auto.pdf") as doc:
    result = doc.read()
    with_entity = {cid for e in result.entities if e.kind in wanted for cid in e.chunk_ids}
    for figure in result.figures():
        if with_entity.intersection(figure.chunk_ids):
            path = out / f"{figure.ref.replace(':', '-')}.png"
            if not path.exists():  # uma vez por figura
                path.write_bytes(doc.crop(figure.page, figure.bbox, grayscale=False))
```

O que o modelo ler na figura passa pela mesma conferência do resto: o
valor que tem regra só vale se a regra confere, e a afirmação sem
referência é descartada.

## Para uma pessoa

Tudo acima vale para uma revisão humana, com a imagem no lugar do modelo.
`docaudit.visualize` desenha as caixas de cada linha na cor do leitor,
`Document.doubts` lista, um `Doubt` por item, o que merece revisão: o valor que falha a verificação,
a linha mal decodificada e, numa digitalização com camada de OCR, o valor em
reais que a camada lê com outro número no mesmo lugar. As referências servem
para anotar: "p3:2 está certo, é erro do documento". Uma ferramenta de revisão
pode usar `Chunk.id` para prender a decisão à linha entre execuções, e a referência
curta para a tela.
