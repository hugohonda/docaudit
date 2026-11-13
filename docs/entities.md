# Entidades padrão

Uma [entidade](glossary.md#entidade) é um valor que uma
[verificação](glossary.md#verificacao) achou no texto lido. A verificação
(`Check`) junta a forma impressa de um campo e a regra que diz se o valor é
possível. Cada entidade sai em `Result.entities` com o estado que a regra deu
e as linhas de onde ela veio. A política `evidence` usa as mesmas verificações
para encaminhar páginas.

Esta página lista o que sai por padrão e o que cada estado prova. Como
declarar os campos do seu tipo de documento está em
[Declarar os campos do seu documento](how-to/checks.md).

## O que sai por padrão

```python
import docaudit

result = docaudit.process("mandado.pdf")
for e in result.entities:
    print(e.page, e.kind, e.value, e.state, e.printed)
```

Com o PDF nato-digital de [Formato da resposta](response/index.md#exemplo), a
saída é esta:

```text
0 CNJ 9001087-60.2022.8.26.0390 confirmed None
0 CPF 529.982.247-25 confirmed None
0 valor em reais R$ 12.500,00 well_formed None
0 data 10/03/2024 well_formed None
0 CPF 111.444.777-30 failed text_layer
```

`DEFAULT_ENTITIES` tem doze campos:

| campo | `kind` | regra | estado quando confere |
|---|---|---|---|
| CPF | `CPF` | dois dígitos verificadores, em módulo 11 | `confirmed` |
| CNPJ | `CNPJ` | dois dígitos verificadores, no CNPJ numérico ou alfanumérico | `confirmed` |
| número de processo | `CNJ` | módulo 97 da Resolução CNJ 65/2008 | `confirmed` |
| valor em reais | `valor em reais` | a grafia brasileira: grupos de três, vírgula e dois centavos, depois de `R$` ou antes do `C` ou `D` de um extrato | `well_formed` |
| valor em moeda anterior ao real | `valor em moeda anterior ao real` | `Cr$`, `NCr$`, `Cz$`, `NCz$` ou `CR$` na mesma grafia, com centavos opcionais | `well_formed` |
| data | `data` | `dd/mm/aaaa` que existe no calendário | `well_formed` |
| data com dia da semana | `data com dia da semana` | `Quarta-feira, 05 de Janeiro de 2022` ou `segunda-feira, 10/03/2025`: o dia da semana confere com o calendário | `confirmed` |
| data por extenso | `data por extenso` | `1º de março de 2024`, que existe no calendário | `well_formed` |
| folha | `folha` | `fl. 16`, `fls. 5.662` ou `fls: 1002`, com o verso; sem regra de validade | `well_formed` |
| chave de acesso | `chave de acesso` | os 44 dígitos de uma NF-e, CT-e ou NFC-e, juntos ou em grupos de quatro: o dígito em módulo 11, a UF do IBGE, o mês e o modelo | `confirmed` |
| linha digitável de boleto | `linha digitável de boleto` | os 47 dígitos, com ou sem pontos: o dígito de cada campo em módulo 10 e o geral em módulo 11 | `confirmed` |
| código de arrecadação | `código de arrecadação` | os 48 dígitos de uma guia ou conta, em quatro blocos: o dígito de cada bloco e o geral, no módulo que o terceiro dígito indica | `confirmed` |

A lista vale para toda linha, composta pelo programa que gerou o PDF ou lida
por um motor de OCR. Ela sai com qualquer política, inclusive `all_cheap`,
porque achar o valor não custa leitura nenhuma. `process(entities=[...])`
substitui a lista inteira. Sem `entities=`, saem as verificações da política e
depois as de `DEFAULT_ENTITIES`, sem repetir nome.

Depois do rótulo do campo, como `CPF:`, `CPF/MF nº` ou `CNPJ :`, o
identificador vale com ponto, traço, barra ou espaço entre quaisquer dígitos:
`CPF: 22279745836`, `CNPJ : 52849569/0001-20`. É o que fica de um carimbo de
assinatura, ou de um OCR que trocou o ponto. O dígito verificador decide como
na forma de sempre. Sem o rótulo, onze dígitos soltos não contam como CPF,
porque todo telefone e todo protocolo passariam. O valor achado só pelo rótulo
sai em `Result.entities`, mas não encaminha a página.

A [folha](glossary.md#folha) é o número que quem lê os autos cita, e não
coincide com o índice da página. O carimbo no alto da página é a folha daquela
página, e `fls. 16` no corpo de uma decisão aponta para outra. O carimbo, numa
linha de elemento fixo, vai em `Page.folha`. Um intervalo, como `fls. 08/10`,
não casa.

Os três códigos de pagamento, a chave de acesso, a linha digitável e o código
de arrecadação, saem como entidade e não encaminham a página. Eles ficam fora
de `DEFAULT_SIGNALS`. Para encaminhar por um deles, acrescente o sinal à
política: `EvidenceRouter([*DEFAULT_SIGNALS, FailsCheck(NFE_KEY)])`.

`AMOUNT_IN_WORDS` confere o valor em reais contra o mesmo valor por extenso
entre parênteses. Ele fica fora de `DEFAULT_ENTITIES` e entra por escolha.

## Os três estados

O [estado](glossary.md#estado) diz o que a regra provou sobre o valor.

| estado | o que prova | o que não prova |
|---|---|---|
| `confirmed` | a regra tem redundância, como um dígito verificador, e conferiu | nada sobre o resto da linha |
| `well_formed` | a forma é possível | que os dígitos estão certos: `R$ 4.000,00` lido de `R$ 1.000,00` também é bem escrito |
| `failed` | a regra falhou: a leitura errou, ou o documento imprimiu errado | qual dos dois |

O que não casa com a forma de nenhum campo não tem estado. Um valor que a
leitura deformou não aparece em `Result.entities`, e uma página sem valor
`failed` não está por isso certa ([Limites](limits.md#comportamentos-conhecidos)).

`Entity.printed` separa os dois casos de `failed` quando há prova:

| `printed` | quer dizer |
|---|---|
| `text_layer` | o valor veio da camada à vista de uma página nato-digital, onde não há leitor que erre. O erro é do documento |
| o nome de um leitor | outra família leu o mesmo valor inválido no mesmo lugar. O erro é do documento |
| `null` | o erro pode ser de leitura |

`RoutingDecision.reason` dá a conclusão da página. Quando a releitura trouxe
o valor que confere, o motivo diz "corrigido por". Quando nada explicou a
falha, fica o motivo original. O que cada sinal prova está em
[Política, conferência e escalada](concepts/policy.md).

Um valor que a leitura partiu em duas linhas, como `R$` no fim de uma e o
número na seguinte, sai uma vez. As duas linhas ficam em `chunk_ids`, e a caixa
que as contém fica em `bbox`.

## Identificadores fora do padrão

Quatro [identificadores](glossary.md#identificador) com dígito verificador já
vêm prontos e ficam fora de `DEFAULT_ENTITIES`. A tupla `IDENTIFIERS` os
reúne. Eles aparecem só em certos tipos de documento. Fora deles, a forma de
onze dígitos casaria protocolos e telefones, e a política `evidence` gastaria
o leitor caro numa falha que não é do campo.

| campo | `kind` | forma | regra |
|---|---|---|---|
| PIS, PASEP ou NIT | `PIS` | `123.45678.90-1`, ou qualquer pontuação depois de `PIS`, `PASEP` ou `NIT` | um dígito em módulo 11 |
| título de eleitor | `título de eleitor` | `1234 5678 0132`, ou qualquer pontuação depois de `Título de Eleitor`. Os treze dígitos de São Paulo e Minas Gerais só casam depois do rótulo | dois dígitos em módulo 11, e a UF de 01 a 28 |
| CNH | `CNH` | onze dígitos depois de `CNH` ou `Registro` | dois dígitos verificadores |
| RENAVAM | `RENAVAM` | onze dígitos colados a `RENAVAM`, com no máximo `nº` ou dois-pontos entre eles. O número antigo, de nove dígitos, fica de fora | um dígito em módulo 11 |

A CNH e o RENAVAM são impressos como onze dígitos soltos, que nada distingue
de outro número. Só o rótulo diz o que eles são. Por isso o rótulo faz parte
da forma, e o valor fica no grupo `value`, que é o que sai na entidade. O
RENAVAM tem um dígito verificador só, e a forma estreita compensa.

Para extrair os quatro, passe `entities=[*DEFAULT_ENTITIES, *IDENTIFIERS]`.
Para que um deles também encaminhe a página, ponha o `FailsCheck` dele na
política. O exemplo completo está em
[Declarar os campos do seu documento](how-to/checks.md).

## O que fica de fora

A biblioteca não liga uma entidade a um papel: o CPF é "um CPF", e não "o CPF
do réu". Ela não procura nome de pessoa, endereço, nem valor sem forma fixa e
regra de validade. Também não confere se o número do processo é o mesmo em
todas as folhas. Esses passos são de quem lê o resultado, uma pessoa ou um
modelo. Como entregar as entidades a um modelo sem perder a origem de cada uma
está em [Entregar a leitura a um agente](agent.md).
