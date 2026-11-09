# Políticas e verificações

O módulo `docaudit.policies` traz as políticas, que decidem que páginas
encaminhar ao leitor caro, e os sinais com que a política `evidence` decide.
Traz também as verificações, que dizem se um valor é possível, e os formatos
de tarja. A
tabela dos sinais, com o que cada um prova, está em
[Configuração](../configuration.md#politicas). O porquê de cada sinal está em
[Política, conferência e escalada](../concepts/policy.md).

## Políticas

Uma política recebe as páginas classificadas e devolve uma decisão por
página. `process(policy=)` aceita a instância ou o nome de uma das três
embutidas.

::: docaudit.types.TriagePolicy
    options:
      heading_level: 3

::: docaudit.policies.AllCheap
    options:
      heading_level: 3

::: docaudit.policies.AllStrong
    options:
      heading_level: 3

::: docaudit.policies.EvidenceRouter
    options:
      heading_level: 3

::: docaudit.policies.get_policy
    options:
      heading_level: 3

## Sinais

Um sinal conta, numa página, as evidências de que a leitura barata errou.
Zero quer dizer sem evidência. A ordem da lista que a política recebe é a
prioridade.

::: docaudit.policies.Signal
    options:
      heading_level: 3

::: docaudit.policies.LineSignal
    options:
      heading_level: 3

::: docaudit.policies.signal
    options:
      heading_level: 3

::: docaudit.policies.EmptyRead
    options:
      heading_level: 3

::: docaudit.policies.GarbledText
    options:
      heading_level: 3

::: docaudit.policies.MojibakeText
    options:
      heading_level: 3

::: docaudit.policies.FailsCheck
    options:
      heading_level: 3

::: docaudit.policies.DEFAULT_SIGNALS
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.DEFAULT_CHECKS
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.garbled_runs
    options:
      heading_level: 3

::: docaudit.policies.mojibake_in
    options:
      heading_level: 3

::: docaudit.policies.failures
    options:
      heading_level: 3

## Verificações

Uma verificação (`Check`) junta o nome de um campo, a forma impressa dele e a
regra que diz se o valor é possível. Em `process(entities=)`, ela extrai o
valor; dentro de `FailsCheck`, ela também encaminha a página. A tabela das
doze que saem por padrão está em [Entidades padrão](../entities.md).

::: docaudit.policies.Check
    options:
      heading_level: 3

::: docaudit.policies.CPF
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.CNPJ
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.CNJ
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.AMOUNT_BRL
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.AMOUNT_PRE_REAL
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.AMOUNT_IN_WORDS
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.DATE_DMY
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.DATE_WEEKDAY
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.DATE_VERBOSE
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.FOLHA
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.NFE_KEY
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.BOLETO
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.ARRECADACAO
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.PIS
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.VOTER_ID
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.CNH
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.RENAVAM
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.IDENTIFIERS
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.DEFAULT_ENTITIES
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.entities_of
    options:
      heading_level: 3

::: docaudit.policies.fold_lookalikes
    options:
      heading_level: 3

## Formatos de tarja e de folha

Um formato de tarja (`StampFormat`) diz como achar, na camada de texto, a
tarja que o sistema eletrônico do tribunal imprime na margem. Uma forma de
folha é um `Check` com o número no grupo `number`. `process(stamps=)` e
`process(folhas=)` aceitam o objeto ou o nome dele.

::: docaudit.policies.StampFormat
    options:
      heading_level: 3

::: docaudit.policies.ESAJ_STAMP
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.PJE_STAMP
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.PROJUDI_PR_STAMP
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.PROJUDI_GO_STAMP
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.EPROC_STAMP
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.STAMP_FORMATS
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.DEFAULT_STAMPS
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.PROJUDI_PAGE
    options:
      heading_level: 3
      show_attribute_values: false

::: docaudit.policies.FOLHA_FORMATS
    options:
      heading_level: 3
      show_attribute_values: false
