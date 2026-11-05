# Entidades

O que a biblioteca acha no texto lido além do próprio texto: cada valor com
forma impressa e regra de validade, com o estado que a regra deu e a linha
de onde ele saiu. É a lista que `Result.entities` traz, e é o mesmo
mecanismo com que a política `evidence` encaminha páginas. Esta página diz
o que sai por padrão, o que cada estado prova, e como declarar os campos do
seu tipo de documento.

## O que sai por padrão

```python
import docaudit

result = docaudit.process("autos.pdf")
for e in result.entities:
    print(e.page, e.kind, e.value, e.state, e.chunk_ids)
```

```text
0 CNJ 9001087-60.2022.8.26.0390 confirmed ('6323c9c0fc99345c618da7de',)
0 CPF 529.982.247-26 failed ('a0b8e3...',)
0 valor em reais R$ 4.000,00 well_formed ('c1d2...', 'e3f4...')
0 data 10/03/2024 well_formed ('a0b8e3...',)
```

`DEFAULT_ENTITIES` são doze campos:

| campo | `kind` | regra | estado quando confere |
|---|---|---|---|
| CPF | `CPF` | dois dígitos verificadores, módulo 11 | `confirmed` |
| CNPJ | `CNPJ` | dois dígitos verificadores, numérico ou alfanumérico | `confirmed` |
| número de processo | `CNJ` | módulo 97 da Resolução CNJ 65/2008 | `confirmed` |
| valor em reais | `valor em reais` | a grafia brasileira: grupos de três, vírgula, dois centavos, depois de `R$` ou antes do `C` ou `D` de um extrato | `well_formed` |
| valor em moeda anterior ao real | `valor em moeda anterior ao real` | `Cr$`, `NCr$`, `Cz$`, `NCz$` ou `CR$` na mesma grafia, centavos opcionais | `well_formed` |
| data | `data` | `dd/mm/aaaa` que existe no calendário | `well_formed` |
| data com dia da semana | `data com dia da semana` | `Quarta-feira, 05 de Janeiro de 2022` ou `segunda-feira, 10/03/2025`: o dia confere com o calendário | `confirmed` |
| data por extenso | `data por extenso` | `1º de março de 2024`, o fecho de uma peça ou de um contrato, que existe no calendário | `well_formed` |
| folha | `folha` | `fl. 16`, `fls. 5.662` ou `fls: 1002`, a folha dos autos, com o verso; sem regra de validade | `well_formed` |
| chave de acesso | `chave de acesso` | os 44 dígitos de uma NF-e, CT-e ou NFC-e, juntos ou em grupos de quatro: dígito em módulo 11, UF do IBGE, mês e modelo | `confirmed` |
| linha digitável de boleto | `linha digitável de boleto` | os 47 dígitos, com ou sem pontos: o dígito de cada campo em módulo 10 e o geral em módulo 11 | `confirmed` |
| código de arrecadação | `código de arrecadação` | os 48 dígitos de uma guia ou conta, em quatro blocos: o dígito de cada bloco e o geral, no módulo que o terceiro dígito nomeia | `confirmed` |

Depois do rótulo do campo (`CPF:`, `CPF/MF nº`, `CNPJ :`), o id vale com
um ponto, traço, barra ou espaço entre quaisquer dígitos: `CPF: 22279745836`, `CNPJ : 52849569/0001-20`. É o que
fica de um carimbo de assinatura ou de um OCR que trocou o ponto. O dígito
verificador decide como no padrão. Sem o rótulo, onze dígitos soltos não são
CPF, porque todo telefone e protocolo passaria.

A folha é a coordenada que quem lê um auto cita, e não coincide com o índice
da página: o carimbo no alto da folha é a folha daquela página, e `fls. 16`
no corpo de uma decisão aponta para outra. O carimbo, em linha de elemento
fixo, vai em `Page.folha`. Um
intervalo, `fls. 08/10`, não casa.

A lista vale para toda linha, composta pelo tipógrafo ou lida por um motor
de OCR. Ela sai de qualquer política, inclusive `all_cheap`, porque achar
o valor não custa leitura nenhuma. `AMOUNT_IN_WORDS`, o valor em reais
conferido contra o extenso entre parênteses, fica fora da lista padrão e
entra por escolha, como abaixo.

Os três códigos extraem e não encaminham. Têm mais redundância que um
CPF, e uma falha neles é quase sempre leitura errada; ficam fora de
`DEFAULT_SIGNALS` até que uma medição em corpus público os pegue falhando
numa leitura. Para encaminhar por eles,
`EvidenceRouter([*DEFAULT_SIGNALS, FailsCheck(NFE_KEY)])`.

## Os três estados

| estado | o que prova | o que não prova |
|---|---|---|
| `confirmed` | a regra tem redundância e conferiu: um dígito trocado quase nunca passa | nada sobre o resto da linha |
| `well_formed` | a forma é possível | que os dígitos estão certos: `R$ 4.000,00` lido de `R$ 1.000,00` é bem escrito |
| `failed` | a regra falhou: ou a leitura errou, ou o documento imprimiu errado | qual dos dois |

`Entity.printed` separa os dois casos quando a cascata tem prova:
`text_layer` se o valor veio de linha composta, o nome do leitor se outra
família leu o mesmo valor no mesmo lugar, `None` se pode ser leitura.
`RoutingDecision.reason` dá a conclusão da página: "corrigido por" quando a
releitura trouxe o valor que confere, e o motivo original quando nada
explicou. Os detalhes do que cada
sinal prova estão em [Conceitos](concepts.md#a-politica-evidence).

Um valor que a leitura partiu em duas linhas, como `R$` no fim de uma e o
número na seguinte, sai uma vez, com as duas linhas em `chunk_ids` e a
caixa que as contém em `bbox`.

## Entidade e sinal são dois usos da mesma verificação

Um `Check` é um nome, a forma impressa e uma função que diz se o valor é
possível. Ele serve a duas coisas:

- em `entities=`, só extrai: cada valor sai em `Result.entities`;
- em `FailsCheck(check)` dentro da política, também encaminha: a página em
  que um valor falha vai à releitura e ao leitor caro.

Uma verificação posta na política sai nas entidades sem ser pedida duas
vezes. O padrão de `entities=` é: as verificações da política, e depois
`DEFAULT_ENTITIES`, sem repetir nome. Passar `entities=[...]` substitui a
lista inteira.

```python
from docaudit.policies import (
    AMOUNT_IN_WORDS,
    DEFAULT_ENTITIES,
    DEFAULT_SIGNALS,
    EvidenceRouter,
    FailsCheck,
)

result = docaudit.process(
    "edital.pdf",
    policy=EvidenceRouter([*DEFAULT_SIGNALS, FailsCheck(AMOUNT_IN_WORDS)]),  # encaminha
    entities=[*DEFAULT_ENTITIES, AMOUNT_IN_WORDS],  # e extrai
)
```

Por que a data extrai e não encaminha: uma data impossível costuma estar
impressa assim no documento, e reler devolveria o mesmo valor. A data como entidade diz onde está e se existe; como sinal, gastaria
o leitor caro sem consertar nada. A mesma pergunta vale para cada campo
seu: a falha dele aponta leitura errada que reler conserta?

## Um campo do seu tipo de documento

`Check(name, pattern, is_valid, redundant=False)`. Duas regras fazem a
falha provar alguma coisa:

- `pattern` casa só a forma daquele campo. Onze dígitos soltos como CPF
  disparariam em todo telefone e protocolo;
- `is_valid` aceita todo valor verdadeiro. É uma regra de estrutura, como
  um dígito verificador ou o calendário.

`redundant=True` declara que a regra tem redundância, e o valor que confere
sai `confirmed`; sem ele, sai `well_formed`. Declare `True` só com um
dígito verificador ou equivalente: é a diferença entre "este valor está
certo" e "este valor é possível".

```python
import re

from docaudit.policies import DEFAULT_ENTITIES, DEFAULT_SIGNALS, Check, EvidenceRouter, FailsCheck


def cns_is_valid(printed: str) -> bool:
    """O Cartão Nacional de Saúde: quinze dígitos, soma ponderada divisível por 11."""
    digits = printed.replace(" ", "")
    return sum(int(c) * (15 - i) for i, c in enumerate(digits)) % 11 == 0


CNS = Check(
    "CNS",
    re.compile(r"(?<![\d.\-])[12789]\d{2} ?\d{4} ?\d{4} ?\d{4}(?![\d\-])"),
    cns_is_valid,
    redundant=True,
)

result = docaudit.process(
    "prontuario.pdf",
    policy=EvidenceRouter([*DEFAULT_SIGNALS, FailsCheck(CNS)]),
    entities=[*DEFAULT_ENTITIES, CNS],
)
```

As funções `is_valid` do [python-stdnum](https://arthurdejong.org/python-stdnum/)
servem como estão, inclusive para campos de outros países:

```python
from stdnum import iban

IBAN = Check("IBAN", re.compile(r"\bBR\d{2}[0-9A-Z]{25}\b"), iban.is_valid, redundant=True)
```

## Os ids fora do padrão

Quatro ids com dígito verificador já vêm prontos e ficam fora de
`DEFAULT_ENTITIES`: o PIS, o título de eleitor, a CNH e o RENAVAM, na tupla
`IDENTIFIERS`. Aparecem só em certos tipos de documento, e fora
deles a forma de onze dígitos casaria protocolo e telefone por engano, com
a política `evidence` gastando o leitor caro numa falha que não é do campo.
Entram por escolha, como entidade, como sinal, ou os dois:

```python
from docaudit.policies import (
    DEFAULT_ENTITIES,
    DEFAULT_SIGNALS,
    IDENTIFIERS,
    PIS,
    EvidenceRouter,
    FailsCheck,
)

result = docaudit.process(
    "folha.pdf",
    policy=EvidenceRouter([*DEFAULT_SIGNALS, FailsCheck(PIS)]),  # encaminha pelo PIS
    entities=[*DEFAULT_ENTITIES, *IDENTIFIERS],  # extrai os quatro
)
```

| campo | `kind` | forma | regra |
|---|---|---|---|
| PIS, PASEP ou NIT | `PIS` | `123.45678.90-1`, ou qualquer pontuação depois de `PIS`, `PASEP`, `NIT` | dígito em módulo 11 |
| título de eleitor | `título de eleitor` | `1234 5678 0132`, ou qualquer pontuação depois de `Título de Eleitor`; treze dígitos só pelo rótulo | dois dígitos em módulo 11 e a UF de 01 a 28 |
| CNH | `CNH` | onze dígitos depois de `CNH` ou `Registro` | dois dígitos verificadores |
| RENAVAM | `RENAVAM` | onze dígitos colados a `RENAVAM`, com no máximo `nº` ou dois-pontos entre eles; o número antigo de nove dígitos fica de fora | dígito em módulo 11, um só: a forma estreita compensa |

A CNH e o RENAVAM se imprimem como onze dígitos soltos, que nada distingue
de outro número: só o rótulo diz o que são. Por isso o rótulo faz parte da
forma, e o valor fica no grupo `value`, que é o que sai na entidade. Um
`Check` seu faz o mesmo nomeando esse grupo.

## Um perfil por tipo de documento

Nada na biblioteca sabe que tipo de documento está lendo. O que muda de um
acervo para outro são quatro argumentos, e um perfil é só uma função que os
fixa:

| tipo de documento | `cheap=` | sinais da política | `entities=` | `layout=` |
|---|---|---|---|---|
| autos judiciais digitalizados | o padrão | `DEFAULT_SIGNALS` | o padrão | não |
| edital com relação de nome e valor | o padrão | padrão e `FailsCheck(AMOUNT_IN_WORDS)` | padrão e `AMOUNT_IN_WORDS` | `PPDocLayout()` no leitor caro, para a tabela |
| diário oficial em duas colunas | o padrão | `DEFAULT_SIGNALS` | o padrão | `PPDocLayout(drop=())`, para a ordem das colunas |
| notas fiscais | o padrão | padrão e `FailsCheck(NFE_KEY)` | o padrão, que já traz `NFE_KEY` | não |
| folha de pagamento | o padrão | padrão e `FailsCheck(PIS)` | padrão e `PIS` | não |
| contratos nato-digitais | `["text_layer"]` | `DEFAULT_SIGNALS` | o padrão | não |

```python
from docaudit import Budget
from docaudit.backends.ppocr import PPOCR
from docaudit.policies import PIS


def read_payroll(path):
    return docaudit.process(
        path,
        policy=EvidenceRouter([*DEFAULT_SIGNALS, FailsCheck(PIS)]),
        entities=[*DEFAULT_ENTITIES, PIS],
        strong=PPOCR("v6-medium"),
        budget=Budget(max_strong_fraction=0.1),
    )
```

Um sinal que não aponta valor, como um termo de rubrica ou a densidade de
números, também entra na política: ver
[Configuração](configuration.md#um-sinal-proprio). Ele encaminha a página
inteira e não produz entidade.

## O que fica de fora

A biblioteca não liga uma entidade a um papel: o CPF é "um CPF", não "o
CPF do réu". Não procura nome de pessoa, endereço nem o que não tem forma
fixa e regra de validade. Não confere que o número do processo é o mesmo
em todas as folhas. Esses passos pertencem a quem lê o resultado, uma
pessoa ou um modelo, e [Análise por um agente](agent.md) mostra como
entregar as entidades a um modelo sem perder a origem de cada uma.
