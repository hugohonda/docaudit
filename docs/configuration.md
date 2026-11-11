# Configuração

Tudo se configura por argumento de chamada. Não há arquivo de configuração, e
só duas variáveis de ambiente. Os termos desta página estão definidos no
[glossário](glossary.md).

## `process()`

```python
docaudit.process(
    document,
    *,
    policy="all_cheap",
    budget=None,
    cheap=("text_layer", "ppocr"),
    strong=None,
    confirm=None,
    reread="page",
    layout=None,
    trust_layer="visible",
    entities=None,
    stamps=None,
    folhas=None,
    spans=False,
    allow_external=False,
    cache=None,
    dpi=None,
    workers=1,
    pages=None,
    min_raster_fraction=0.0,
)
```

| argumento | tipo | padrão | efeito |
|---|---|---|---|
| `document` | `Path`, `str` ou `bytes` | obrigatório | um PDF, ou uma imagem PNG, JPEG, TIFF, BMP ou WebP. A imagem vira um PDF de uma página por quadro, no DPI que ela declara |
| `policy` | `TriagePolicy` ou nome | `"all_cheap"` | a [política](glossary.md#politica) que decide que páginas encaminhar ao leitor caro; ver [Políticas](#politicas) |
| `budget` | `Budget` | sem teto | o [teto](glossary.md#teto) do leitor caro, em páginas e em segundos; ver [Teto](#teto-budget) |
| `cheap` | sequência de `Reader` ou de nomes | `("text_layer", "ppocr")` | a [cascata](glossary.md#cascata) da etapa barata, em ordem. Vale a primeira leitura não vazia |
| `strong` | `Reader` ou nome | `None` | o leitor caro. Pode ser qualquer `Reader`, inclusive um OCR. `None` desliga a etapa cara |
| `confirm` | `Reader` ou nome | `None` | o leitor de outra [família](glossary.md#familia) que relê a página encaminhada por uma verificação, antes do leitor caro |
| `reread` | `Reread`: `"page"` ou `"region"` | `"page"` | o que o leitor caro recebe: a página inteira, ou o recorte das linhas que falharam |
| `layout` | `Layout` | `None` | o [detector de layout](glossary.md#detector-de-layout) que põe as linhas de todos os leitores na ordem dos blocos da página |
| `trust_layer` | `TrustLayer`: `"visible"` ou `"always"` | `"visible"` | o que fazer com a [camada de OCR](glossary.md#camada-de-ocr) de uma página `searchable_scan`; ver abaixo |
| `entities` | sequência de `Check` | as da política e `DEFAULT_ENTITIES` | as verificações cujos valores saem em `Result.entities`; ver [Entidades padrão](entities.md) |
| `stamps` | sequência de `StampFormat` ou de nomes | `DEFAULT_STAMPS`, o e-SAJ | os formatos de [tarja](glossary.md#tarja) procurados na camada de texto, para `Page.stamp`. `[]` não procura nenhum |
| `folhas` | sequência de `Check` ou de nomes | `FOLHA`, `fls. N` | as formas de folha procuradas nas linhas de elemento fixo, para `Page.folha`. `[]` não procura nenhuma |
| `spans` | `bool` | `False` | põe em cada `Entity.span` o começo e o fim do valor no texto das linhas dele |
| `allow_external` | `bool` | `False` | autoriza os leitores [externos](glossary.md#externo), que enviam a página para fora da máquina |
| `cache` | `ModelCallCache` | `None` | guarda cada leitura; uma segunda execução lê do disco |
| `dpi` | `int` | por página | fixa o DPI de renderização de todas as páginas; ver abaixo |
| `workers` | `int` | `1` | threads na etapa barata, e na etapa cara quando o leitor caro é externo |
| `pages` | conjunto de `int` | todas | os índices a processar, a partir de zero. As outras páginas nem são carregadas |
| `min_raster_fraction` | `float` | `0.0` | numa página nato-digital, a fração da página abaixo da qual um raster não lido não vai ao leitor de pixels; ver abaixo |

`trust_layer="visible"` não usa a camada de OCR como leitura. O leitor de
pixels seguinte da cascata lê a página, e a camada entra como primeira família
da releitura, sem custo. `"always"` lê a camada como está, e só a evidência no
texto encaminha a página.

Sem `dpi`, cada página com imagem é renderizada na resolução da imagem, presa
ao intervalo de `MIN_NATIVE_DPI` a `MAX_NATIVE_DPI`. Uma página sem imagem é
renderizada em `DEFAULT_DPI`. Os três vivem em `docaudit.pdf`.

`workers` acima de `1` rende com um motor que solta o GIL do Python fora do
lock do PDF, como o Tesseract. Com que leitor isso vale a pena está em
[Desempenho](performance.md).

`stamps=` aceita os nomes de `STAMP_FORMATS`: `e-saj`, `pje`, `projudi-pr`,
`projudi-go` e `eproc`. `folhas=` aceita os nomes de `FOLHA_FORMATS`: `folha`
e `pagina-projudi`. Uma forma de folha própria traz o número no grupo
`number`. Como declarar a tarja de outro sistema está na receita
[Tarja e folha de outro sistema](recipes/stamps.md).

`spans=True` acrescenta dois inteiros por entidade ao JSON. Por isso vem
desligado.

!!! warning "`allow_external` envia páginas para fora da máquina"
    Sem `allow_external=True`, pedir um leitor externo levanta
    `ExternalBackendError` antes de o documento ser aberto. A regra vale para
    `cheap=`, `confirm=` e `strong=`. O que sai e o que fica no disco está em
    [Segurança dos dados](security.md).

!!! warning "`min_raster_fraction` não está calibrado"
    O logotipo e o brasão do cabeçalho custam uma leitura de pixels que não
    traz linha útil. O valor que os separa de uma figura com texto depende do
    acervo, e nenhuma medição o fixou. `0.0` lê todos os rasters. O raster que
    fica de fora continua em `Page.unread` e em `Result.figures()`, sem linha.

### `Document`

`Document` recebe no construtor `cheap`, `strong`, `confirm`, `layout`,
`trust_layer`, `cache`, `dpi` e `allow_external`. `Document.read()` recebe
`policy`, `budget`, `reread`, `workers`, `pages`, `entities`, `stamps`,
`folhas` e `spans`. A política padrão de `Document.read()` é `"evidence"`.
`min_raster_fraction` existe só em `process()`. A assinatura completa está em
[Ponto de entrada](reference/entry.md).

## Leitores

Cada leitor tem um nome registrado, que `cheap=`, `strong=` e `confirm=`
aceitam como texto, e uma classe, que aceita parâmetros.

| nome | classe | extra | o que lê |
|---|---|---|---|
| `text_layer` | `TextLayerReader()` | nenhum | a camada de texto do PDF, uma linha por trecho, sem renderizar |
| `tesseract` | `TesseractOCR(lang=None, config="")` | `tesseract` e o binário | a página renderizada em tons de cinza, uma linha por trecho |
| `ppocr` | `PPOCR(models="v5-latin", ...)` | `ppocr`, ou `openvino` | a página renderizada em cor, uma linha por trecho, com confiança |
| `vlm` | `VLM(url, model, ...)` | `vlm`; o detector vem do extra `layout` | a página, ou cada região de layout dela, por um modelo de visão e linguagem |

O nome da tabela é o que `cheap=` e `strong=` aceitam. O nome que fica em
`Chunk.source` é o do leitor, e o do `PPOCR` traz os pesos: `ppocr-v5-latin`
na etapa barata e `ppocr-v6-medium` na etapa cara saem distintos. Como
instalar cada extra está em [Instalação](install.md).

### `PPOCR`

```python
PPOCR(models="v5-latin", *, rec=None, keys=None, det=None, threads=None, engine="auto")
```

| parâmetro | efeito |
|---|---|
| `models` | os pesos do detector e do reconhecedor. `"v5-latin"`, o padrão, é o PP-OCRv5 mobile com o reconhecedor latino. `"v6-medium"` é o PP-OCRv6 medium, com um reconhecedor de muitas línguas e custo maior |
| `rec`, `keys` | um reconhecedor ONNX próprio e o dicionário de caracteres com que ele foi treinado. Vêm juntos. O detector continua o de `models` |
| `det` | um detector ONNX próprio. Com ele, nada do detector é baixado |
| `threads` | as threads do motor dentro de uma inferência; ver abaixo |
| `engine` | o motor: `"auto"`, `"onnxruntime"`, `"openvino"` ou `"cuda"`; ver abaixo |

Os pesos baixam na primeira leitura para `<DOCAUDIT_CACHE_DIR>/models`.
`PPOCR().prepare()` baixa os pesos e abre as sessões na hora. Chame-o na
construção da imagem de contêiner, ou no início do processo. Assim a leitura
não depende da rede, e um arquivo que falta falha antes do documento.

Cada arquivo próprio entra no nome do leitor pelo começo do hash dele. Com
`rec=` e `keys=`, o nome fica `ppocr-v5-latin+<hash do reconhecedor>`. Com
`det=`, o nome ganha antes `+det=<hash do detector>`. Os hashes também entram
em `output_version`: um treino novo gravado no mesmo caminho não recebe a
leitura guardada do anterior.

```python
from docaudit.backends.ppocr import PPOCR

# o nome do leitor fica ppocr-v5-latin+<hash de rec.onnx>
reader = PPOCR(rec="ajuste/rec.onnx", keys="ajuste/ppocrv5_latin_dict.txt")
```

`threads=None` deixa o padrão do motor: todos os núcleos da máquina. A exceção
é o processo com menos núcleos disponíveis que a máquina, como num contêiner
com `cpuset`, e então vale o número do processo. A cota de CPU de um contêiner
sem `cpuset` não aparece para o processo: passe o número de vCPUs. `threads`
não entra em `output_version`, porque muda o tempo e não a leitura.

`engine="auto"` escolhe o OpenVINO quando o extra `openvino` está instalado, e
o ONNX Runtime quando não está. `"onnxruntime"` e `"openvino"` fixam um dos
dois. `"cuda"` roda no ONNX Runtime da GPU. O leitor confere a sessão e falha
na primeira leitura se ela não ficou na GPU, em vez de ler na CPU com o nome
da GPU. Cada motor parte e arredonda algumas linhas de um jeito, e por isso o
motor entra em `output_version`, salvo o ONNX Runtime na CPU.

Quem fixa uma leitura em produção, ou compara execuções pelo cache, passa
`engine=` explícito. Com `"auto"`, instalar o extra `openvino` troca o motor, e
com ele a chave do cache, sem aviso. Como instalar o OpenVINO e o ONNX Runtime
da GPU está em [Instalação](install.md).

### `TesseractOCR`

```python
TesseractOCR(lang=None, config="")
```

`lang` é o código de idioma do Tesseract. Sem ele, vale a variável
`DOCAUDIT_OCR_LANG`, cujo padrão é `por`. O pacote de idioma precisa estar
instalado no sistema. `config` recebe opções do motor, como `"--psm 6"`.

### `VLM`

```python
VLM(
    url="http://127.0.0.1:8089",
    model="glm-ocr",
    *,
    served=None,
    api_key=None,
    prices=None,
    layout=None,
    concurrency=1,
    timeout=600.0,
    max_tokens=4096,
    reasoning=None,
    retries=0,
)
```

| parâmetro | efeito |
|---|---|
| `url` | a base do servidor, sem `/v1`. Um host que não é a própria máquina torna o leitor externo |
| `model` | o conjunto de prompts: `"glm-ocr"`, o padrão, `"paddleocr-vl"`, para o PaddleOCR-VL-1.6, ou `"generic"`, com um prompt de transcrição em português |
| `served` | o nome do modelo no pedido. É obrigatório num servidor fora da máquina. Num servidor local, sem ele, o leitor pergunta ao servidor qual é o único modelo servido |
| `api_key` | a credencial, enviada como `Bearer` |
| `prices` | dólares por milhão de tokens de entrada e de saída. Com ele, `spent.usd` tem valor |
| `layout` | um `PPDocLayout`. Com ele, uma chamada e um trecho por região de layout. Sem ele, a página inteira numa chamada |
| `concurrency` | chamadas simultâneas por página, uma por região |
| `timeout` | segundos por chamada |
| `max_tokens` | o teto de tokens de saída por chamada. A resposta cortada no teto faz a página falhar |
| `reasoning` | o esforço de raciocínio, enviado como `reasoning_effort` (`"none"`, `"low"`...). `None` deixa o padrão do servidor. Entra em `output_version` |
| `retries` | quantas vezes repetir uma chamada que falhou de modo passageiro; ver abaixo |

`retries` repete a chamada que o servidor recusou por carga (HTTP 429 ou 5xx),
a que esgotou o `timeout` e a que perdeu a conexão no meio. Isso vale para o
servidor local e para o externo. `0`, o padrão, não repete. A espera segue o
`Retry-After` do servidor, ou dobra a cada tentativa a partir de um segundo.
Esgotadas as tentativas, a página falha e o documento segue.

A conexão recusada é o único caso em que o servidor local e o externo
diferem. No servidor local, ela quer dizer que o servidor não está no ar: o
leitor levanta `ConnectionError`, e o documento para. No externo, ela é uma
falha passageira como as outras.

Os servidores que falam o formato do leitor, e os comandos de cada um, estão
em [Ligar um modelo de visão e linguagem](how-to/vlm.md).

### `PPDocLayout`

```python
PPDocLayout(threshold=0.5, drop=DROP_DEFAULT, *, threads=None)
```

Detecta as regiões de layout de uma página com o PP-DocLayoutV3, no ONNX
Runtime. Os pesos baixam na primeira detecção para
`<DOCAUDIT_CACHE_DIR>/models`.

| parâmetro | efeito |
|---|---|
| `threshold` | a pontuação mínima de uma região. É o valor de referência do exportador, sem calibração |
| `drop` | os rótulos que não viram região. `DROP_DEFAULT` tira `aside_text`, `footer`, `footnote`, `header`, `image`, `number` e `seal`, que não são conteúdo para um leitor por região. Entra em `output_version` |
| `threads` | as threads do ONNX Runtime dentro de uma inferência, como em `PPOCR`. `None` usa todos os núcleos |

Para ordenar a leitura com `process(layout=...)`, passe `drop=()`. Toda linha
precisa de um bloco, inclusive as do cabeçalho, do rodapé e da tarja. Sem
bloco, a linha vai ao bloco mais próximo e sai fora do lugar.

## Políticas

| nome | classe | o que encaminha |
|---|---|---|
| `all_cheap` | `AllCheap()` | nenhuma página |
| `all_strong` | `AllStrong()` | todas as páginas, até o teto de `Budget` |
| `evidence` | `EvidenceRouter(signals=DEFAULT_SIGNALS, *, min_failures=1)` | só a página em que algum sinal disparou, na ordem dos sinais |

`all_cheap` e `all_strong` decidem antes de qualquer leitura. A página
encaminhada por elas não passa pela etapa barata, com duas exceções: sem
leitor caro (`strong=None`), e quando o teto `max_seconds` a tira do leitor
caro. `evidence` decide depois da etapa barata, e a página encaminhada é lida
nas duas etapas.

### Sinais da política `evidence`

Um [sinal](glossary.md#sinal) conta, numa página, as evidências de que a
leitura barata errou. A ordem da lista é a prioridade. Quando o teto não cobre
todas as páginas com evidência, vence o primeiro sinal da lista que disparou.
Dentro dele, vence a página com mais ocorrências. Essa ordem não foi medida.

`DEFAULT_SIGNALS` traz os sete sinais marcados como padrão, na ordem da tabela. Os dois últimos entram por escolha.

| sinal | padrão | o que conta |
|---|---|---|
| `EmptyRead()` | sim | a leitura que não trouxe texto nenhum. Uma folha em branco também volta vazia |
| `GarbledText()` | sim | caracteres que só uma decodificação quebrada produz: o de substituição U+FFFD, os da área de uso privado, que saem de uma fonte sem tabela ToUnicode, e os de controle, exceto tabulação e quebra de linha. Vale também em texto composto, porque reler os pixels conserta o que a decodificação quebrou |
| `FailsCheck(CPF)`, `FailsCheck(CNPJ)`, `FailsCheck(CNJ)` | sim | o identificador na pontuação de sempre com dígito verificador errado. O CNPJ pode ser alfanumérico |
| `FailsCheck(AMOUNT_BRL)` | sim | o valor em reais que a grafia brasileira não permite: duas vírgulas, espaço entre grupos de milhar, letra no lugar de dígito, grupo sem três dígitos |
| `FailsCheck(AMOUNT_PRE_REAL)` | sim | o mesmo, no valor em cruzeiro, cruzado ou cruzeiro real (`Cr$`, `NCr$`, `Cz$`, `NCz$`, `CR$`) |
| `MojibakeText()` | não; pede o extra `mojibake` | o texto decodificado com a codificação errada, como `honor·rios` por `honorários`. A camada extrai sem erro e parece texto, mas a tabela ToUnicode está errada |
| `FailsCheck(AMOUNT_IN_WORDS)` | não | o valor em reais que não bate com o mesmo valor por extenso entre parênteses, como `R$ 214.000,00 (duzentos e quatorze mil reais)`. Pega o dígito trocado que forma outro valor bem escrito |

`FailsCheck` só conta texto que um motor reconheceu: a camada de uma página
`searchable_scan`, e o que um leitor de pixels leu em qualquer página. Na
camada à vista de uma página nato-digital, o erro é do documento, e reler
devolveria o mesmo valor. `DEFAULT_CHECKS` reúne os `FailsCheck` de
`DEFAULT_SIGNALS`.

Para acrescentar um sinal, passe a lista inteira, na ordem que quiser:

```python
from docaudit.policies import AMOUNT_IN_WORDS, DEFAULT_SIGNALS, EvidenceRouter, FailsCheck

policy = EvidenceRouter([*DEFAULT_SIGNALS, FailsCheck(AMOUNT_IN_WORDS)])
```

Uma verificação ou um sinal do seu tipo de documento está em
[Declarar os campos do seu documento](how-to/checks.md). O porquê de cada
sinal padrão está em [Política, conferência e escalada](concepts/policy.md).

!!! warning "`min_failures` não está calibrado"
    `EvidenceRouter(min_failures=n)` só encaminha por verificação a página com
    pelo menos `n` valores que falham, somados entre os `FailsCheck`. A leitura
    vazia e o texto mal decodificado encaminham com uma ocorrência. O padrão,
    `1`, encaminha toda falha. Nenhuma medição fixou outro valor. Com
    `reread="region"`, a página abaixo do mínimo também deixa de reler o
    recorte das suas linhas.

## Teto (`Budget`)

```python
Budget(max_strong_pages=None, max_strong_fraction=None, max_seconds=None)
```

O teto limita o leitor caro numa chamada, em páginas e em segundos.

| campo | limite |
|---|---|
| `max_strong_pages` | quantas páginas o leitor caro lê, no máximo |
| `max_strong_fraction` | a fração das páginas que o leitor caro lê, arredondada para cima: `0.2` num documento de quatro páginas permite uma |
| `max_seconds` | os segundos de parede, contados do início da chamada, depois dos quais o leitor caro não começa página nova |

Com as duas formas em páginas, vale a mais restritiva. O teto de páginas vale
para qualquer política, na ordem de prioridade dela. A página que passa dele
fica com a leitura barata. A política `evidence` não encaminha página sem
evidência, e um teto folgado sobra.

A página encaminhada que o leitor caro começaria depois de `max_seconds` fica
com a leitura barata, e o motivo vai em `RoutingDecision.steps`. A etapa
barata e a releitura por outra família terminam sempre: o teto corta só a
etapa cara, que é a que custa. A decisão da política fica como está, e
`spent.pages_strong` conta o que rodou.

Tokens e dólares não têm teto. `Result.spent` os relata, e quem chama decide o
que fazer com eles. A prioridade entre documentos também é de quem chama.

## Cache

```python
from docaudit import ModelCallCache

cache = ModelCallCache("leituras.sqlite")
```

`ModelCallCache(path=None)` guarda cada leitura de página num arquivo SQLite.
Sem caminho, grava em `<DOCAUDIT_CACHE_DIR>/calls.sqlite`. Um mesmo arquivo
serve a várias threads e a vários processos. O que entra na chave está em
[Origem e cache](concepts/provenance.md). O que isso quer dizer para os dados
está em [Segurança dos dados](security.md).

## Variáveis de ambiente

| variável | padrão | efeito | quando é lida |
|---|---|---|---|
| `DOCAUDIT_CACHE_DIR` | `~/.cache/docaudit` | onde ficam o cache sem caminho explícito e os pesos dos modelos | quando um `ModelCallCache` sem caminho é criado, e quando os pesos são carregados |
| `DOCAUDIT_OCR_LANG` | `por` | o idioma do Tesseract quando `TesseractOCR(lang=None)` | quando o `TesseractOCR` é construído |
