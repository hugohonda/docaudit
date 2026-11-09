# Declarar os campos do seu documento

Este guia acrescenta à leitura um campo que a biblioteca não traz, como o
Cartão Nacional de Saúde de um prontuário. O campo pode só sair na lista de
entidades ou também encaminhar a página ao leitor caro. Os doze campos que já
vêm prontos, e o que cada estado prova, estão em
[Entidades padrão](../entities.md).

## Extrair ou também encaminhar

Uma verificação (`Check`) junta o nome do campo, a forma impressa e a regra
de validade. Ela serve a dois usos:

| onde entra | o que faz |
|---|---|
| `entities=[...]` | só extrai: cada valor sai em `Result.entities`, com estado e linha de origem |
| `FailsCheck(check)` na política | também encaminha: a página em que um valor falha vai à releitura e ao leitor caro |

Uma verificação posta na política sai nas entidades sem ser pedida duas
vezes. Sem `entities=`, a lista é: as verificações da política e depois
`DEFAULT_ENTITIES`, sem repetir nome. Passar `entities=[...]` troca a lista
inteira.

```python
from docaudit import process
from docaudit.policies import (
    AMOUNT_IN_WORDS,
    DEFAULT_ENTITIES,
    DEFAULT_SIGNALS,
    EvidenceRouter,
    FailsCheck,
)

result = process(
    "edital.pdf",
    policy=EvidenceRouter([*DEFAULT_SIGNALS, FailsCheck(AMOUNT_IN_WORDS)]),  # encaminha
    entities=[*DEFAULT_ENTITIES, AMOUNT_IN_WORDS],  # e extrai
)
```

`AMOUNT_IN_WORDS` confere o valor em reais contra o mesmo valor por extenso
entre parênteses, como `R$ 214.000,00 (duzentos e quatorze mil reais)`.

Para decidir entre os dois usos, pergunte: a falha deste campo aponta uma
leitura errada que reler conserta? A data responde que não. Uma data
impossível em geral está impressa assim no documento, e reler devolve o mesmo
valor. Por isso a data só extrai. O CPF (Cadastro de Pessoas Físicas) responde que sim, e por isso
encaminha. O porquê completo está em
[Política, conferência e escalada](../concepts/policy.md).

## Um campo seu

A assinatura completa é
`Check(name, pattern, is_valid, redundant=False, labeled=None, alike=None)`.
Duas regras fazem a falha provar alguma coisa:

- `pattern` casa só a forma daquele campo. Onze dígitos soltos como CPF
  casariam todo telefone e protocolo.
- `is_valid` aceita todo valor verdadeiro. É uma regra de estrutura, como um
  dígito verificador ou o calendário.

`redundant=True` diz que a regra tem redundância: o valor que confere sai
`confirmed`. Sem ele, sai `well_formed`, que só diz que a forma é possível.
Declare `True` só quando há dígito verificador ou regra equivalente.

O Cartão Nacional de Saúde (CNS) tem quinze dígitos. O definitivo começa por
1 ou 2, o provisório por 7, 8 ou 9. Nos dois, a soma de cada dígito
multiplicado pelo peso, de 15 a 1, é múltipla de 11:

```python
import re

from docaudit import process
from docaudit.policies import DEFAULT_ENTITIES, DEFAULT_SIGNALS, Check, EvidenceRouter, FailsCheck


def cns_is_valid(printed: str) -> bool:
    """Quinze dígitos cuja soma ponderada, com pesos de 15 a 1, é múltipla de 11."""
    digits = [int(c) for c in printed if c.isdigit()]
    weighted = sum(d * w for d, w in zip(digits, range(15, 0, -1)))
    return len(digits) == 15 and weighted % 11 == 0


CNS = Check(
    "CNS",
    re.compile(r"(?<![\d.\-])[12789]\d{2} ?\d{4} ?\d{4} ?\d{4}(?![\d\-])"),
    cns_is_valid,
    redundant=True,
)

result = process(
    "prontuario.pdf",
    policy=EvidenceRouter([*DEFAULT_SIGNALS, FailsCheck(CNS)]),
    entities=[*DEFAULT_ENTITIES, CNS],
)
for entity in result.entities:
    if entity.kind == "CNS":
        print(entity.page, entity.value, entity.state)
```

```text
0 123 4567 8901 2380 confirmed
```

As funções `is_valid` do
[python-stdnum](https://arthurdejong.org/python-stdnum/) servem como estão,
inclusive para campos de outros países. Elas aceitam o valor com a
pontuação:

```python
import re

from stdnum import iban

from docaudit.policies import Check

IBAN = Check("IBAN", re.compile(r"\bBR\d{2}[0-9A-Z]{25}\b"), iban.is_valid, redundant=True)
```

### Um campo que só o rótulo distingue

Alguns números não têm forma própria. O registro da CNH são onze dígitos
soltos, iguais a um protocolo ou a um telefone. Nesse caso o rótulo entra em
`pattern`, e o valor fica num grupo chamado `value`, como em
`(?:CNH|Registro):? ?(?P<value>\d{11})`. A verificação e a entidade ficam só
com o valor. É assim que `CNH` e `RENAVAM` são declarados.

`labeled=` é outra coisa: a forma do campo depois do rótulo, fora da
pontuação padrão, como `CPF: 22279745836`. O valor assim achado sai em
`Result.entities`, mas não encaminha a página: `FailsCheck` olha só
`pattern`.

`alike=` recebe uma função que diz se o valor que falha é uma troca que
leitores de famílias diferentes fazem igual. Um exemplo é o ponto no lugar da
vírgula decimal numa tabela digitalizada. Nessa troca, duas famílias que
leem o mesmo valor inválido não provam que o erro está impresso. A página
segue ao leitor caro.

## Os identificadores fora do padrão

Quatro identificadores com dígito verificador vêm prontos e ficam fora de
`DEFAULT_ENTITIES`: o PIS, o título de eleitor, a CNH e o RENAVAM, na tupla
`IDENTIFIERS`. Eles só aparecem em certos tipos de documento. Fora deles, a
forma casaria protocolos e telefones, e a política gastaria o leitor caro
numa falha que não é do campo. Entram por escolha, como entidade, como
sinal, ou dos dois jeitos:

```python
from docaudit import process
from docaudit.policies import (
    DEFAULT_ENTITIES,
    DEFAULT_SIGNALS,
    IDENTIFIERS,
    PIS,
    EvidenceRouter,
    FailsCheck,
)

result = process(
    "folha-de-pagamento.pdf",
    policy=EvidenceRouter([*DEFAULT_SIGNALS, FailsCheck(PIS)]),  # encaminha pelo PIS
    entities=[*DEFAULT_ENTITIES, *IDENTIFIERS],  # extrai os quatro
)
```

A forma e a regra de cada um estão em [Entidades padrão](../entities.md).

## Um sinal próprio

Um sinal é uma função `(page, chunks) -> int` com nome. Zero quer dizer sem
evidência. Ele encaminha a página inteira e não produz entidade, o que serve
para um critério sem forma fixa, como um termo de rubrica:

```python
from docaudit import process
from docaudit.policies import DEFAULT_SIGNALS, EvidenceRouter, signal


@signal("rubrica com valor")
def heading_with_money(page, chunks):
    text = " ".join(c.text for c in chunks).lower()
    has_heading = any(t in text for t in ("custas", "honorários", "multa"))
    return text.count("r$") if has_heading else 0


result = process("documento.pdf", policy=EvidenceRouter([heading_with_money, *DEFAULT_SIGNALS]))
for decision in result.decisions:
    print(decision.page, decision.signals)
```

A posição na lista é a prioridade quando um teto não cobre todas as páginas.
A contagem de cada sinal que disparou sai em `RoutingDecision.signals`, pelo
nome. Um sinal assim acerta num tipo de documento e erra noutro: meça-o nos
seus dados antes de confiar nele.

## Um perfil por tipo de documento

Nada na biblioteca sabe que tipo de documento está lendo. De um acervo para
outro mudam quatro argumentos, e um perfil é uma função que os fixa:

| tipo de documento | `cheap=` | sinais da política | `entities=` | detector de layout |
|---|---|---|---|---|
| autos judiciais digitalizados | o padrão | `DEFAULT_SIGNALS` | o padrão | não |
| edital com relação de nome e valor | o padrão | o padrão e `FailsCheck(AMOUNT_IN_WORDS)` | o padrão e `AMOUNT_IN_WORDS` | `PPDocLayout()` no leitor caro, para a tabela |
| diário oficial em duas colunas | o padrão | `DEFAULT_SIGNALS` | o padrão | `layout=PPDocLayout(drop=())`, para a ordem das colunas |
| notas fiscais | o padrão | o padrão e `FailsCheck(NFE_KEY)` | o padrão, que já traz `NFE_KEY` | não |
| folha de pagamento | o padrão | o padrão e `FailsCheck(PIS)` | o padrão e `PIS` | não |
| contratos nato-digitais | `["text_layer"]` | `DEFAULT_SIGNALS` | o padrão | não |

```python
from pathlib import Path

from docaudit import Budget, Result, process
from docaudit.backends.ppocr import PPOCR
from docaudit.policies import DEFAULT_ENTITIES, DEFAULT_SIGNALS, PIS, EvidenceRouter, FailsCheck


def read_payroll(path: Path) -> Result:
    return process(
        path,
        policy=EvidenceRouter([*DEFAULT_SIGNALS, FailsCheck(PIS)]),
        entities=[*DEFAULT_ENTITIES, PIS],
        strong=PPOCR("v6-medium"),
        budget=Budget(max_strong_fraction=0.1),
    )
```

As receitas [Relação de nome e valor](../recipes/name-value-list.md),
[Diário oficial em duas colunas](../recipes/two-columns.md) e
[Notas fiscais e boletos](../recipes/invoices.md) mostram três desses
perfis completos.

## Onde entra cada característica

Uma regra sua pode entrar em cinco lugares, conforme o que ela precisa ver:

| quando decide | gancho | o que vê | exemplo |
|---|---|---|---|
| antes de ler a página | um `Reader` seu na cascata `cheap=`, que devolve vazio nas páginas que não são dele | o substrato, a evidência dele e as dimensões | mandar páginas grandes só de imagem a um motor e o resto a outro |
| depois da leitura barata | um sinal ou um `Check` em `EvidenceRouter([...])` | a página e as linhas dela | termos de rubrica, densidade de valores, um identificador do seu domínio |
| sobre o documento inteiro | uma `TriagePolicy` sua, passada em `policy=` | todas as páginas e todas as leituras baratas | as páginas entre um título e o seguinte |
| entre documentos | quem chama, com `pages=` ou um `Budget` por chamada | o que quem chama sabe | escolher que processos recebem o leitor caro |
| na leitura cara | um `Reader` em `strong=`, como `VLM(layout=PPDocLayout(drop=...))` | a página renderizada | outro modelo, outro conjunto de regiões |

O leitor que devolve vazio está em [Escrever um leitor](../writing-a-reader.md).
O `Protocol` de `TriagePolicy` está na
[referência do resultado](../reference/types.md).
