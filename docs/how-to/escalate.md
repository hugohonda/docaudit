# Escalar só o que falhou

Este guia liga um leitor caro e faz com que ele leia só as páginas em que a
leitura barata falhou numa verificação. Cada passo acrescenta um argumento a
`process()`. A razão de ler nessa ordem está em
[Política, conferência e escalada](../concepts/policy.md).

Dois verbos aparecem o tempo todo. A política **encaminha** a página: marca
que ela merece o leitor caro. O leitor caro **escala** a página: lê de fato.
Os dois só coincidem quando há leitor caro e o teto permite. Os outros termos
estão no [Glossário](../glossary.md).

## Ver o que a política encaminharia

Comece sem leitor caro. A política `evidence` lê todas as páginas com a cascata
barata. Depois encaminha só a página em que um sinal disparou. Os sinais são a
leitura vazia, o texto mal decodificado e o valor que falha a verificação do
campo, como um CPF (Cadastro de Pessoas Físicas) com o dígito verificador
errado.

```python
from docaudit import Tier, process

result = process("documento.pdf", policy="evidence")
for decision in result.decisions:
    if decision.tier is Tier.STRONG:
        print(decision.page, decision.reason, decision.signals)
print(result.spent.pages_strong)  # 0: sem strong=, nenhuma página escala
```

```text
0 1 x CNJ que falha a verificação {'CNJ que falha a verificação': 1}
0
```

Sem `strong=`, a decisão fica registrada e nenhuma página escala. É o ensaio
da política: mostra quantas páginas iriam ao leitor caro antes de você pagar
por ele. Os sinais que `evidence` usa por padrão estão em
[Configuração](../configuration.md).

## Ligar o leitor caro

O leitor caro é um `Reader` como os baratos. Qualquer leitor serve, inclusive
um motor de reconhecimento óptico de caracteres (OCR) maior:

```python
from docaudit import process
from docaudit.backends.ppocr import PPOCR

result = process("documento.pdf", policy="evidence", strong=PPOCR("v6-medium"))
print(result.spent.pages_strong)
```

O leitor caro relê a página encaminhada. Cada linha dele entra no lugar das
linhas baratas cujo centro ela cobre. Ela é recusada, e a linha barata fica,
quando perde um valor que a barata trazia certo ou quando não conserta o
valor que falhou ali. As regras estão em
[A leitura cara passa pelas mesmas verificações](../concepts/policy.md#a-leitura-cara-passa-pelas-mesmas-verificacoes).

O exemplo usa o PP-OCR `v6-medium` porque ele roda sem servidor. Não é uma
recomendação: o que cada leitor custa e o que compra está em
[Desempenho](../performance.md#leitores).

Para usar um modelo de visão e linguagem como leitor caro, veja
[Ligar um modelo de visão e linguagem](vlm.md).

## Reler antes com outra família

Um CPF errado pode estar impresso assim no documento. Nesse caso, reler com o
leitor caro gasta dinheiro e devolve o mesmo valor. `confirm=` relê a página
com um leitor de outra família antes do leitor caro. Família é um motor de
outra arquitetura e outro treino, cujos erros não coincidem com os do
primeiro.

```python
from docaudit import process
from docaudit.backends.ppocr import PPOCR
from docaudit.backends.tesseract import TesseractOCR

result = process(
    "documento.pdf",
    policy="evidence",
    confirm=TesseractOCR(),
    strong=PPOCR("v6-medium"),
)
for decision in result.decisions:
    print(decision.page, decision.tier, decision.reason)
```

A releitura tem três desfechos:

| desfecho | `RoutingDecision.reason` | o que acontece |
|---|---|---|
| a outra família leu o mesmo valor inválido | `erro do documento: <leitor> leu o mesmo` | a página fica com a leitura barata, e a entidade ganha `printed`. Exceção: a troca que as famílias fazem juntas, declarada em `Check.alike`, não prova nada, e a página segue ao leitor caro |
| a outra família leu, no mesmo lugar, um valor que confere | `corrigido por <leitor>` | as linhas trocam, e a página fica sem leitor caro |
| outra coisa | o motivo original | a página segue ao leitor caro |

`confirm=` não tem relação com o estado `confirmed` de uma entidade. Ele
relê toda página encaminhada em que um valor falha uma verificação, qualquer
que seja o sinal que a encaminhou. A página sem valor que falha, como a de
leitura vazia, vai direto ao leitor caro. O que
`printed` prova está em [Entidades padrão](../entities.md).

## Pôr um teto

`Budget` limita o leitor caro em páginas e em tempo:

```python
from docaudit import Budget, process
from docaudit.backends.ppocr import PPOCR

result = process(
    "documento.pdf",
    policy="evidence",
    strong=PPOCR("v6-medium"),
    budget=Budget(max_strong_pages=10, max_strong_fraction=0.2, max_seconds=300),
)
```

| campo | limita |
|---|---|
| `max_strong_pages` | o número de páginas que o leitor caro lê |
| `max_strong_fraction` | a fração das páginas processadas, arredondada para cima: `0.2` em quatro páginas permite uma |
| `max_seconds` | o tempo de parede, contado do início da chamada; depois dele o leitor caro não começa página nova |

Com os dois tetos em páginas, vale o menor. Quando o teto não cobre todas as
páginas encaminhadas, passam primeiro as do sinal que vem antes na lista da
política. A página que ficou de fora mantém a leitura barata, com `tier`
igual a `cheap` e o motivo do sinal que disparou nela. A página que o teto de páginas deixou de fora também não passa pela
releitura por outra família: a releitura só vê a página que continua
encaminhada. A leitura barata e a releitura por outra família terminam
sempre: `max_seconds` corta só a etapa cara.

O teto vale para qualquer política, inclusive `all_strong`. Tokens e dólares
não têm teto. `Result.spent` os relata quando o leitor caro sabe contá-los, e
quem chama decide o que fazer com eles.

## Reler só o recorte

Por padrão, o leitor caro lê a página inteira. Com `reread="region"`, ele
recebe só o recorte das linhas cujo valor falhou e substitui só o que leu
ali. O resto da página fica com a leitura barata.

```python
from docaudit import process
from docaudit.backends.ppocr import PPOCR

result = process(
    "documento.pdf",
    policy="evidence",
    strong=PPOCR("v6-medium"),
    reread="region",
)
print(result.spent.regions_strong)  # páginas em que o leitor caro leu só o recorte
```

A página vai inteira, nos dois modos, quando disparou nela um sinal que não
é uma verificação (`FailsCheck`), como leitura vazia ou texto mal
decodificado.

## Exigir mais de uma falha

`EvidenceRouter(min_failures=n)` só encaminha por verificação a página com
pelo menos `n` valores que falham, somados entre os campos. Leitura vazia e
texto mal decodificado continuam encaminhando com uma ocorrência.

```python
from docaudit import process
from docaudit.backends.ppocr import PPOCR
from docaudit.policies import EvidenceRouter

result = process(
    "documento.pdf",
    policy=EvidenceRouter(min_failures=3),
    strong=PPOCR("v6-medium"),
)
```

!!! warning "Parâmetro não calibrado"
    O padrão, `1`, encaminha toda falha. Nenhum outro valor de `min_failures`
    foi medido. Se usar outro, meça no seu acervo quantos valores errados
    deixam de ser relidos.

## Conferir o que aconteceu

Cada decisão da política conta o que houve com a página:

```python
from docaudit import process
from docaudit.backends.ppocr import PPOCR

result = process("documento.pdf", policy="evidence", strong=PPOCR("v6-medium"), reread="region")
for decision in result.decisions:
    print(decision.page, decision.tier, decision.reason)
    for step in decision.steps:
        print("   ", step)
print(result.spent.pages_strong, result.spent.pages_strong_failed)
```

```text
0 strong 1 x CNJ que falha a verificação
    tier barato: ppocr-v5-latin leu 12 linha(s)
    política: 1 x CNJ que falha a verificação
    ppocr-v6-medium leu 1 recorte(s) das linhas que falharam: 1 linha(s); substituiu 0 da leitura barata, ficaram 12
    1 linha(s) do leitor caro recusada(s): leu o mesmo valor inválido (1000123-47.2024.8.26.0100); os dois leitores podem errar juntos
1 0
```

- `steps` diz, na ordem, quem leu, o que a política decidiu, o que a
  releitura concluiu e quantas linhas o leitor caro trocou.
- `seconds` dá, por etapa, os segundos que a página gastou.
- `spent.pages_strong` conta as páginas que o leitor caro leu de fato, e
  `pages_strong_failed`, as que ele não conseguiu ler.
- `spent.lines_strong_rejected` conta as linhas do leitor caro recusadas,
  por perder um valor que conferia ou por não explicar o que falhou.

A página que o leitor caro não conseguiu ler fica com a leitura barata e
emite um `RuntimeWarning`. Os campos de `RoutingDecision` e de `Spent` estão
em [Campos do resultado](../response/fields.md). Para ver a página com a
caixa de cada linha na cor do leitor, use `docaudit.visualize`.
