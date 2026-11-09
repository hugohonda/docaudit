# Política, conferência e escalada

A [política](../glossary.md#politica) decide que páginas [encaminhar](../glossary.md#encaminhar) ao
[leitor caro](../glossary.md#leitor-caro). Encaminhar é a decisão: `RoutingDecision.tier` igual a
`"strong"`. [Escalar](../glossary.md#escalar) é a leitura de fato, contada em `spent.pages_strong`.
Sem `strong=`, a política encaminha e nada escala: é o modo de ensaio de
uma política.

As políticas embutidas se resolvem pelo nome:

| nome | o que encaminha |
|---|---|
| `all_cheap` | nada; o padrão |
| `all_strong` | toda página |
| `evidence` | só a página cuja leitura barata provou ter falhado |

Nenhuma política encaminha páginas ao acaso. Essa linha de base, que mede
o ganho de uma cascata, fica com quem avalia. O passo a passo de uma chamada está em
[Escalar só o que falhou](../how-to/escalate.md).

## Teto (`Budget`)

`Budget` é um [teto](../glossary.md#teto) opcional do leitor caro, em
páginas e em tempo:

| campo | o que limita |
|---|---|
| `max_strong_pages` | quantas páginas vão ao leitor caro |
| `max_strong_fraction` | a fração das páginas processadas, arredondada para cima |
| `max_seconds` | o tempo de parede da execução a partir do qual a etapa cara não começa página nova |

Com os dois limites em páginas, vale o mais restritivo. A política
`evidence` corta pela ordem de prioridade dos sinais, `all_strong` pela
ordem das páginas, e uma política própria pela ordem em que devolve as
decisões. A página que passa do teto fica na [etapa barata](../glossary.md#etapa-barata), e o motivo
diz isso.

Quando `max_seconds` vence, a releitura por outra família termina mesmo
assim. A página que o teto de tempo alcançou fica com a leitura barata, que
é feita então se a política a tinha dispensado. Tokens e dólares não têm
teto: são relatados em
[`Result.spent`](../response/fields.md#spent).

## Decidir antes ou depois da leitura barata

Toda política declara `needs_reads`.

Com `needs_reads=False`, a política decide só pelo substrato, antes de
qualquer leitura. É o caso de `all_cheap` e `all_strong`. A página
encaminhada não paga a etapa barata, com duas exceções: quando não há
`strong=`, e quando o `max_seconds` a tirou do leitor caro.

Com `needs_reads=True`, `process()` lê toda página na etapa barata e passa
as leituras a `decide(pages, budget, reads)`. É o caso de `evidence`. A
página encaminhada é lida nas duas etapas. A leitura cara substitui a barata só onde leu. Um leitor por
região descarta o cabeçalho, o rodapé e a tarja da margem, e essas linhas
ficam da leitura barata.

## A política `evidence`

`EvidenceRouter` encaminha só a página cuja leitura barata provou ter
falhado. O motivo fica em `RoutingDecision.reason`.

A prova vem de [sinais](../glossary.md#sinal). Um sinal é uma função que
conta, numa página, as ocorrências de leitura errada. A prioridade entre
páginas segue três critérios, nesta ordem:

1. a posição, na lista, do primeiro sinal que disparou;
2. dentro do mesmo sinal, mais ocorrências primeiro;
3. o índice da página.

Os sinais padrão, `DEFAULT_SIGNALS`, são estes, nesta ordem:

- `EmptyRead`, a leitura vazia;
- `GarbledText`, o texto mal decodificado;
- `FailsCheck` de CPF (Cadastro de Pessoas Físicas);
- `FailsCheck` de CNPJ (Cadastro Nacional da Pessoa Jurídica);
- `FailsCheck` do número CNJ, a numeração única do Conselho Nacional de
  Justiça;
- `FailsCheck` de valor em reais e de valor em moeda anterior ao real.

Todos são categóricos, sem limiar ajustado. A tabela com
o que cada um procura está em [Configuração](../configuration.md). A ordem
padrão da lista não foi medida.

`FailsCheck` recebe uma [verificação](../glossary.md#verificacao) (`Check`):
o nome do campo, a forma impressa e uma função que diz se o valor é
possível. O sinal conta os valores que falham, e a decisão cita o campo:
`1 x CPF que falha a verificação`.

O campo só conta em texto escrito por máquina: a camada de uma página
`SEARCHABLE_SCAN` e o que um leitor de pixels leu em qualquer página. Na
camada à vista de uma página nato-digital, o erro é do documento, e reler
devolveria o mesmo erro.

Os falsos positivos conhecidos são dois:

- Uma página em branco volta vazia, e `EmptyRead` dispara.
- Um documento que imprime um identificador ou uma data errados dispara, e
  reler devolve o mesmo valor. A releitura por outra família separa esse
  caso, abaixo.

Ficam fora dos sinais padrão a data que não existe no calendário e a
palavra que mistura dois alfabetos. Um piso de confiança também fica fora.
A faixa de valores da confiança muda de um motor para outro, e um piso
seria um número sem medição. `MojibakeText`, do extra `mojibake`, acha texto
decodificado com a codificação errada, e entra na lista só quando pedido.

Sem evidência, a política não encaminha nada.

### O mínimo de falhas

`EvidenceRouter(min_failures=n)` encaminha por verificação só a página com
pelo menos `n` valores que falham, somados entre os `FailsCheck`. A leitura
vazia e o texto mal decodificado encaminham com uma ocorrência. O padrão,
`1`, encaminha toda falha.

Reler a página inteira conserta onde a leitura barata errou em série, como
numa lista densa digitalizada em baixa resolução. Na página com um só valor
errado, a releitura custa a página inteira por um valor. O mínimo também
vale com `reread="region"`, em que o recorte já é barato: ali ele corta
essa releitura. A página que fica na etapa barata guarda o valor que falha
em `signals` e nas entidades, e o motivo diz que ela ficou abaixo do
mínimo.

!!! warning "`min_failures` não é calibrado"
    O valor que compensa depende do leitor caro e do acervo. Meça nos seus
    documentos antes de subir o mínimo.

## Os três estados

A mesma verificação que encaminha a página também produz
`Result.entities`. Cada [entidade](../glossary.md#entidade) é um valor que a
verificação casou, com as linhas de origem e um de três estados:

| estado | o que a verificação diz |
|---|---|
| `confirmed` | a regra tem redundância e confere, como o dígito verificador de um CPF |
| `well_formed` | a forma e a regra passam, sem redundância: um valor bem escrito, uma data que existe |
| `failed` | a regra falha: erro de leitura ou erro impresso no documento |

A diferença entre os dois primeiros é a redundância (`Check.redundant`). Um
valor em reais bem escrito pode ter um dígito trocado. Um CPF com um dígito
trocado falha o dígito verificador.

Num valor `failed`, `Entity.printed` diz quem mostra que o erro é do
documento. `text_layer` quer dizer que o valor veio da camada composta, que
não tem leitor a errar. O nome de um leitor quer dizer que outra família
leu o mesmo valor inválido no mesmo lugar. `None` quer dizer que o erro
pode ser de leitura.

Uma verificação na política encaminha e extrai. Uma verificação em
`process(entities=)` só extrai. As entidades padrão estão em
[Entidades](../entities.md).

## Reler com outra família antes do leitor caro

Uma [família](../glossary.md#familia) é um motor de outra arquitetura e
outro treino, cujos erros não coincidem com os do primeiro.
`process(..., confirm=TesseractOCR())` relê com outra família a página que
uma verificação encaminhou, antes do leitor caro. O nome `confirm=` não tem
relação com o estado `confirmed`.

Numa página `SEARCHABLE_SCAN`, a primeira família é a própria camada de OCR,
que já está lida. `confirm=` vem depois, e a primeira família que decide
encerra. Há três desfechos:

| a releitura traz | a página | o motivo |
|---|---|---|
| os mesmos valores inválidos | fica na etapa barata | `erro do documento` |
| no lugar de cada valor inválido, um valor que confere, e nenhum inválido restante | fica na etapa barata, com as linhas trocadas | `corrigido por` |
| outra coisa | segue ao leitor caro | |

Uma leitura errada também pode conferir. Por isso a troca exige o mesmo
lugar e nenhum valor inválido restante.

Há uma exceção ao primeiro desfecho. Algumas trocas de caractere acontecem
igual em leitores de famílias diferentes, e a verificação as declara em
`Check.alike`. Nelas, duas famílias que leem o mesmo valor inválido não
provam o erro impresso: a página segue ao leitor caro, e a entidade sai sem
`printed`.

A página encaminhada só por leitura vazia ou por texto mal decodificado não
passa pela releitura. Não há valor inválido a comparar.

O Tesseract relê a página inteira. `confirm=` compensa quando o leitor caro
é bem mais caro que ele, como um modelo de visão e linguagem. Compensa
também quando importa separar o erro impresso no documento do erro de
leitura. `Result.spent` conta `pages_confirmed`, `pages_confirmed_same`,
`pages_confirmed_fixed` e `seconds_confirm`.

## Reler só o recorte

Uma verificação diz em que linha a leitura falhou: `FailsCheck.failing`
devolve cada valor inválido com o trecho em que ele está. Com
`process(..., reread="region")`, o leitor caro recebe um
[recorte](../glossary.md#recorte) por valor inválido. O recorte é a menor
caixa que contém as linhas do valor, que são duas quando ele quebra na
linha. O recorte não tem folga em volta. O leitor caro substitui só o que
leu ali, e o resto da página fica da leitura barata.

Mesmo com `reread="region"`, a página vai inteira quando disparou nela um
sinal que não aponta linha: leitura vazia, texto mal decodificado ou um
sinal próprio. Um recorte ali deixaria o resto da falha na página. Numa
política sem verificação, toda página vai inteira. O padrão de `reread` é
`"page"`, a página inteira.

`Result.spent.regions_strong` conta as páginas em que o leitor caro leu só
os recortes. O recorte entra no cache com a caixa na chave: uma caixa
diferente é uma leitura diferente.

## A leitura cara passa pelas mesmas verificações

A leitura cara substitui a barata só onde leu: a linha barata cujo centro
cai numa caixa da leitura cara sai. A linha barata fora dessas caixas fica,
como a tarja da margem. Um leitor que devolve a caixa da página inteira não
deixa nada da leitura barata.

Mesmo dentro das caixas, a linha cara entra só quando não perde nada que a
barata tinha certo. Ela é recusada, e a linha barata fica, nestes casos:

- Ela cobre uma linha barata com um valor que uma verificação da política
  confere, e não traz esse valor.
- Ela cobre uma linha barata com um número de vírgula decimal e milhar no
  lugar, e não traz esse número. Vale sem o `R$`, porque numa tabela o
  símbolo fica no cabeçalho. A linha cara que lê `15.062.39` onde a barata
  leu `15.062,39` é recusada.
- No lugar de um valor que falhou, ela traz o mesmo valor inválido, ou
  traz outra coisa que não confere. Só a linha cara com o valor que confere
  conserta.

O leitor caro não é declarado de outra família. Quando ele repete o valor
inválido, isso não marca `Entity.printed`: só `confirm=` e a camada de OCR
provam o erro do documento.

`Result.spent.lines_strong_rejected` conta as recusas, e
`RoutingDecision.steps` diz o porquê de cada uma. A linha recusada no lugar
de um valor que falhou fica em `Result.others`, ao lado da linha barata.

Na página encaminhada por texto mal decodificado e lida inteira pelo
leitor caro, a linha barata mal decodificada fora das caixas dele sai. Ela
é lixo por definição.

O leitor caro que falha numa página, com `RuntimeError`, deixa a página com
a leitura barata e a conta em `pages_strong_failed`. Um servidor ausente,
com `ConnectionError`, interrompe o documento.

## Sinais e verificações próprios

A lista de sinais é sua. Um sinal é uma função `(page, chunks) -> int`; o
decorador `signal` dá nome a ela. Uma verificação é um campo com forma
impressa e regra de validade. Os dois entram na lista que `EvidenceRouter`
recebe, e a posição na lista é a prioridade. O passo a passo está em
[Declarar os campos do seu documento](../how-to/checks.md).

## O que aconteceu com cada página

`RoutingDecision.steps` conta o que `process()` fez com a página, uma frase
por passo e na ordem:

- quem leu na etapa barata, e quantas linhas;
- o que a política decidiu;
- o que a releitura por outra família concluiu;
- o que o leitor caro leu, e quantas linhas substituiu.

`RoutingDecision.seconds` traz os segundos de cada etapa que tocou a
página. `visualize` desenha, na imagem de cada página, a caixa de cada
linha na cor do leitor que a leu. `Result.spent` relata o gasto da
chamada, sem o que o cache poupou; as chaves estão em
[Campos do resultado](../response/fields.md#spent).
