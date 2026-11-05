# Configuração

Tudo se configura por argumento de chamada. Não há arquivo de configuração,
e só duas variáveis de ambiente.

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
)
```

| argumento | tipo | padrão | efeito |
|---|---|---|---|
| `document` | `Path`, `str` ou `bytes` | obrigatório | um PDF, ou uma imagem PNG, JPEG, TIFF, BMP ou WebP. A imagem vira um PDF de uma página por quadro, no DPI que ela declara |
| `policy` | `TriagePolicy` ou nome | `"all_cheap"` | quem decide as páginas que escalam. `"all_cheap"` não escala nenhuma, `"all_strong"` escala todas, `"evidence"` escala só onde a leitura barata falhou numa verificação |
| `budget` | `Budget` | sem teto | quantas páginas podem chegar ao leitor caro |
| `cheap` | lista de `Reader` ou nomes | `("text_layer", "ppocr")` | a cascata barata, em ordem. A primeira leitura não vazia vence |
| `strong` | `Reader` ou nome | `None` | o leitor caro. Pode ser qualquer `Reader`, inclusive um OCR. `None` desliga a escalada |
| `confirm` | `Reader` ou nome | `None` | leitor de outra família que relê a página encaminhada por uma verificação, antes do leitor caro |
| `trust_layer` | `TrustLayer`: `"visible"` ou `"always"` | `"visible"` | a camada de texto de uma `searchable_scan`: `"visible"` não a lê como leitura, o leitor de pixels lê a página e a camada entra como primeira família da releitura; `"always"` a lê como está |
| `reread` | `Reread`: `"page"` ou `"region"` | `"page"` | o que o leitor caro recebe: a página inteira, ou o recorte das linhas que falharam |
| `layout` | `Layout` | `None` | detector de regiões que põe as linhas de todos os leitores na ordem dos blocos da página |
| `entities` | lista de `Check` | as da política e `DEFAULT_ENTITIES` | os campos que saem em `Result.entities`, com estado e linha de origem; ver [Entidades](entities.md) |
| `stamps` | lista de `StampFormat` ou nomes de `STAMP_FORMATS` (`e-saj`, `pje`, `projudi-pr`, `projudi-go`, `eproc`) | `DEFAULT_STAMPS`, o e-SAJ | as tarjas procuradas na camada de texto, para `Page.stamp`. `[]` não procura nenhuma; ver [a tarja de outro sistema](recipes.md#a-tarja-e-a-folha-de-outro-sistema) |
| `folhas` | lista de `Check` ou nomes de `FOLHA_FORMATS` (`folha`, `pagina-projudi`) | `FOLHA`, `fls. N` | as formas de folha procuradas nas linhas de elemento fixo, para `Page.folha`; o número vem no grupo `number`. `[]` não procura nenhuma |
| `spans` | `bool` | `False` | põe em cada `Entity.span` o começo e o fim do valor no texto das linhas dele: dois inteiros a mais por entidade no JSON |
| `allow_external` | `bool` | `False` | autoriza leitores que enviam a página para fora da máquina; ver [Segurança dos dados](security.md) |
| `cache` | `ModelCallCache` | `None` | guarda cada leitura; uma segunda execução lê do disco |
| `dpi` | `int` | por página | fixa o DPI de renderização. Sem ele, cada página com imagem é renderizada na resolução da imagem, presa a `[150, 300]`, e uma sem imagem a 200 |
| `workers` | `int` | `1` | threads no tier barato, e no tier caro quando o leitor é hospedado (`external`). O ganho vem de um motor que solta o GIL fora do lock do PDF, como o Tesseract; ver [Desempenho](performance.md) |
| `pages` | conjunto de `int` | todas | os índices a processar, a partir de zero. As outras páginas nem são carregadas |

`Document` recebe os mesmos leitores, `layout`, `trust_layer`, `cache`, `dpi` e
`allow_external` no construtor, e `policy`, `budget`, `reread`, `workers`,
`pages`, `entities`, `stamps`, `folhas` e `spans` em `read()`. A política padrão de `Document.read()` é
`"evidence"`.

## Leitores

Cada leitor tem um nome registrado, que `cheap=`, `strong=` e `confirm=` aceitam
como texto, e uma classe, que aceita parâmetros.

| nome | classe | extra | o que lê |
|---|---|---|---|
| `text_layer` | `TextLayerReader` | núcleo | a camada de texto do PDF, uma linha por trecho, sem renderizar |
| `tesseract` | `TesseractOCR(lang=None, config="")` | `tesseract` e o binário | a página renderizada em tons de cinza, uma linha por trecho |
| `ppocr` | `PPOCR(models="v5-latin")` | `ppocr` | a página renderizada em cor, uma linha por trecho, com confiança |
| `vlm` | `VLM(url, model, ...)` | `vlm`; o detector de layout vem do extra `layout` | a página ou cada região dela, por um modelo de visão e linguagem |

O nome da tabela é o que `cheap=` e `strong=` aceitam como texto. O nome que
fica em `Chunk.source` é o do leitor, e o do `PPOCR` traz os pesos:
`ppocr-v5-latin` no primeiro nível e `ppocr-v6-medium` no segundo saem
distintos.

### `PPOCR`

| `models=` | detecção e reconhecimento |
|---|---|
| `"v5-latin"` | PP-OCRv5 mobile, reconhecedor latino. O padrão |
| `"v6-medium"` | PP-OCRv6 medium, reconhecedor multilíngue, a quatro vezes o custo. Para o segundo nível |

O custo de cada um está em [Desempenho](performance.md#leitores). Os
pesos baixam na primeira leitura para `<DOCAUDIT_CACHE_DIR>/models`.
`threads=` fixa as threads do motor dentro de uma inferência; `None`, o
padrão, usa todos os núcleos, o certo para um processo só. Com vários
processos lendo ao mesmo tempo, cada um disputa todos os núcleos: ver
[a receita de lote](recipes.md#lote-de-muitos-autos). Não entra em `output_version`: muda o
tempo, não a leitura.
`PPOCR().prepare()` baixa e abre as sessões na hora: chame na construção da
imagem e no início do processo, para a leitura não depender da rede e para
que o arquivo que falta falhe antes do documento, em vez de página a página.
O detector baixa também com `rec=`.

Um reconhecedor próprio, como o de um ajuste fino, entra por `rec=` e
`keys=`: o ONNX e o dicionário de caracteres com que ele foi treinado. O
detector continua o de `models=`.

```python
PPOCR(rec="ajuste/rec.onnx", keys="ajuste/ppocrv5_latin_dict.txt")
```

O nome do leitor ganha o começo do hash dos pesos, `ppocr-v5-latin+79bb133dca00`,
e cada linha diz qual ajuste a leu. O hash dos pesos e o do dicionário entram
em `output_version`: um treino novo no mesmo caminho não recebe a leitura
guardada do anterior.

`engine=` escolhe o motor. Na GPU, `engine="cuda"` roda a detecção e o reconhecimento no CUDA do ONNX
Runtime. Pede o `onnxruntime-gpu` no lugar do `onnxruntime`: os dois não
convivem no mesmo ambiente. O pacote do pip, da versão 1.21 em diante, traz o
CUDA e o cuDNN, sem instalação no sistema.

```bash
uv pip uninstall onnxruntime && uv pip install "onnxruntime-gpu[cuda,cudnn]"
```

```python
PPOCR(engine="cuda")
```

O ONNX Runtime que não acha o CUDA cai na CPU sem falhar; o leitor confere a
sessão e falha na primeira leitura em vez de ler na CPU com o nome da GPU. A
GPU parte algumas linhas de outro jeito e lê alguns caracteres diferentes,
e por isso o motor entra em `output_version`: o cache não troca uma leitura
pela outra. O custo está em [Desempenho](performance.md#leitores).

Na CPU, o OpenVINO roda os mesmos arquivos ONNX que o ONNX Runtime em cerca de
um terço do tempo. Ele vem com o extra `openvino`, e com o extra instalado é o
motor padrão (`engine="auto"`); sem ele, o padrão é o ONNX Runtime.
`engine="onnxruntime"` fixa o ONNX Runtime mesmo com o extra.

Quem fixa uma leitura em produção, ou compara execuções pelo cache, passa
`engine=` explícito. Com `"auto"`, instalar o extra numa máquina troca o
motor, e com ele a chave do cache, sem aviso.

```bash
uv add 'docaudit[ppocr,openvino]'
```

A borda de uma caixa pode andar um ou dois pixels entre os motores, porque o
pós-processamento do detector arredonda diferente. Por isso o motor também entra em
`output_version`.

### `TesseractOCR`

`lang` é o código de idioma do Tesseract. Sem ele, vale
`DOCAUDIT_OCR_LANG`, cujo padrão é `por`. O pacote de idioma precisa estar
instalado. `config` recebe flags do motor, como `"--psm 6"`.

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
)
```

| parâmetro | efeito |
|---|---|
| `url` | a base do servidor, sem `/v1`. Um host que não é a própria máquina torna o leitor externo |
| `model` | o preset de prompts: `"glm-ocr"`, o padrão, `"paddleocr-vl"`, para o PaddleOCR-VL-1.6, ou `"generic"`, com um prompt de transcrição em português, para um modelo hospedado |
| `served` | o nome do modelo no pedido; obrigatório num servidor fora da máquina. Num servidor local, sem ele, o leitor pergunta ao servidor qual é o único modelo servido |
| `api_key` | credencial, enviada como `Bearer` |
| `prices` | dólares por milhão de tokens de entrada e de saída; faz `spent.usd` existir |
| `layout` | um `PPDocLayout`. Com ele, uma chamada e um trecho por região, e a região dentro de outra é lida uma vez; sem ele, a página inteira numa chamada |
| `concurrency` | chamadas simultâneas por página, uma por região |
| `timeout` | segundos por chamada |
| `max_tokens` | teto de tokens de saída por chamada. Uma resposta cortada no teto falha a página |
| `reasoning` | o esforço de pensamento, enviado como `reasoning_effort` (`"none"`, `"low"`, ...); `None` deixa o padrão do servidor. Entra em `output_version` |

### Servidores para o leitor `vlm`

O leitor fala o formato de chat da OpenAI, com a imagem embutida em base64.
Qualquer servidor que fale esse formato serve.

| servidor | comando | `VLM(...)` |
|---|---|---|
| llama.cpp | `llama-server -m model.gguf --mmproj mmproj.gguf --port 8089 -np 4 -c 32768` | `VLM(layout=PPDocLayout(), concurrency=4)` |
| vLLM | `vllm serve <modelo>` | `VLM("http://127.0.0.1:8000", "generic", layout=PPDocLayout())` |
| SGLang | `python -m sglang.launch_server --model-path <modelo> --port 30000` | `VLM("http://127.0.0.1:30000", "generic", layout=PPDocLayout())` |
| endpoint hospedado | o do fornecedor | `VLM(url, "generic", served=..., api_key=...)` e `allow_external=True` em `process()` |

Os comandos e os pesos do llama.cpp para os dois presets estão em
[Começando](getting-started.md#um-modelo-de-visao-e-linguagem). Num servidor
local que sirva mais de um modelo, passe `served=`.

### `PPDocLayout`

`PPDocLayout(threshold=0.5, drop=DROP_DEFAULT)` detecta regiões com o
PP-DocLayoutV3 em ONNX Runtime. `threshold` é a pontuação mínima de uma
região; o valor é o de referência do exportador, sem calibração. `drop` são os
rótulos que não viram região: por padrão `aside_text`, `footer`, `footnote`,
`header`, `image`, `number` e `seal`, que não são conteúdo para um leitor
por região. Para ordenar a leitura com `process(layout=...)`, use `drop=()`:
toda linha precisa de um bloco, inclusive as do cabeçalho, do rodapé e da
tarja da margem, ou vai ao bloco mais próximo e sai fora do lugar.

## Políticas

| nome | classe | decide |
|---|---|---|
| `all_cheap` | `AllCheap` | nenhuma página escala |
| `all_strong` | `AllStrong` | todas escalam, ignorando o teto |
| `evidence` | `EvidenceRouter(signals=DEFAULT_SIGNALS, min_failures=1)` | escala, na ordem dos sinais, só a página em que algum sinal disparou; por verificação, só com `min_failures` valores que falham |

`DEFAULT_SIGNALS` é, em ordem: leitura vazia, texto mal decodificado, e
`FailsCheck` de CPF, CNPJ, número CNJ e valor em reais. O que cada um prova
está em [Conceitos](concepts.md#a-politica-evidence).

`AMOUNT_IN_WORDS` confere o valor contra o mesmo valor por extenso entre
parênteses, `R$ 214.000,00 (duzentos e quatorze mil reais)`. Pega a troca de
dígito que forma outro valor bem escrito, que a grafia não vê. Fica fora do
padrão e entra por escolha:

```python
from docaudit.policies import AMOUNT_IN_WORDS, DEFAULT_SIGNALS, EvidenceRouter, FailsCheck

policy = EvidenceRouter([*DEFAULT_SIGNALS, FailsCheck(AMOUNT_IN_WORDS)])
```

### Uma verificação própria

Um `Check` junta um nome, a forma impressa de um campo e uma função que diz
se o valor é possível. `FailsCheck(check)` o transforma em sinal, que
encaminha a página; o mesmo `Check` em `entities=` só extrai o valor. O
que cada uso produz, e `redundant=`, estão em [Entidades](entities.md).

```python
import re

from docaudit.policies import DEFAULT_SIGNALS, Check, EvidenceRouter, FailsCheck


def cns_is_valid(printed: str) -> bool:
    """O Cartão Nacional de Saúde: 15 dígitos, soma ponderada múltipla de 11."""
    d = [int(c) for c in printed if c.isdigit()]
    return len(d) == 15 and sum(a * b for a, b in zip(d, range(15, 0, -1))) % 11 == 0


CNS = Check("CNS", re.compile(r"(?<!\d)\d{3} ?\d{4} ?\d{4} ?\d{4}(?!\d)"), cns_is_valid)
policy = EvidenceRouter([*DEFAULT_SIGNALS, FailsCheck(CNS)])
```

As funções `is_valid` do [python-stdnum](https://arthurdejong.org/python-stdnum/)
servem como estão:

```python
from stdnum import iban

IBAN = Check("IBAN", re.compile(r"\bBR\d{2}[0-9A-Z]{25}\b"), iban.is_valid)
policy = EvidenceRouter([*DEFAULT_SIGNALS, FailsCheck(IBAN)])
```


`Check.alike` é opcional: uma função que diz se o valor que falha é uma
troca que leitores de famílias diferentes fazem igual, como o ponto no
lugar da vírgula decimal numa tabela digitalizada. Nessa troca, duas
famílias que leem o mesmo valor inválido não provam o erro impresso: a
página segue ao leitor caro, e a entidade sai sem `printed`. As
verificações entre os sinais padrão estão em `DEFAULT_CHECKS`.

### Um sinal próprio

Um sinal é uma função `(page, chunks) -> int` com nome. Zero quer dizer sem
evidência. A posição na lista é a prioridade.

```python
from docaudit.policies import DEFAULT_SIGNALS, EvidenceRouter, signal


@signal("rubrica com valor")
def heading_with_money(page, chunks):
    text = " ".join(c.text for c in chunks).lower()
    has_heading = any(t in text for t in ("custas", "honorários", "multa"))
    return text.count("r$") if has_heading else 0


policy = EvidenceRouter([heading_with_money, *DEFAULT_SIGNALS])
```

A contagem de cada sinal que disparou sai em `RoutingDecision.signals`, pelo
nome. Um sinal de rubrica acerta num tipo de documento e erra noutro: quem o
usa o mede contra os próprios dados.

### Onde entra cada característica

| grão | gancho | o que vê | exemplo |
|---|---|---|---|
| página, antes de ler | um `Reader` próprio na cascata `cheap=`, que devolve vazio nas páginas que não são dele e deixa o seguinte ler | substrato e a sua evidência, dimensões | mandar páginas grandes só imagem a um motor e o resto a outro |
| página, depois da leitura barata | um `Signal` ou um `Check` em `EvidenceRouter([...])`; a ordem da lista é a prioridade | a página e os chunks dela | termos de rubrica, densidade de valores, um identificador do seu domínio |
| documento | uma `TriagePolicy` própria, passada como instância em `policy=` | todas as páginas e todas as leituras baratas | "as páginas depois de um título até o próximo" |
| entre documentos | quem chama, por `pages=` ou um `Budget` por chamada | o que quem chama sabe | decidir quais autos recebem o leitor caro |
| o que o leitor caro faz | um `Reader` em `strong=`; `VLM(layout=PPDocLayout(drop=...))` | a página renderizada | outro modelo, outro conjunto de regiões |

## Orçamento

```python
Budget(max_strong_pages=None, max_strong_fraction=None)
```

Um teto opcional, em páginas, de quantas páginas chegam ao leitor caro numa
chamada. Com as duas unidades, vale a mais restritiva. A fração é
arredondada para baixo: `max_strong_fraction=0.2` num documento de quatro
páginas permite zero escaladas. Sem nenhuma das duas, a política decide sem
teto. A política `evidence` não escala página sem evidência, e um teto
folgado sobra.

Tempo, tokens e dólares não têm teto: são relatados em `Result.spent`, e quem
chama decide o que fazer com eles. A prioridade entre documentos também é de
quem chama.

## Cache

```python
from pathlib import Path

from docaudit import ModelCallCache

cache = ModelCallCache(Path(".cache/docaudit.sqlite"))
```

Sem caminho, o cache grava em `<DOCAUDIT_CACHE_DIR>/calls.sqlite`. Vários
processos podem partilhar o mesmo arquivo: quem abre ou grava espera o outro
terminar. A chave e o que ela protege estão em
[Conceitos](concepts.md#cache).

## Variáveis de ambiente

Lidas a cada chamada.

| variável | padrão | efeito |
|---|---|---|
| `DOCAUDIT_OCR_LANG` | `por` | idioma do Tesseract quando `TesseractOCR(lang=None)` |
| `DOCAUDIT_CACHE_DIR` | `~/.cache/docaudit` | onde ficam o cache sem caminho explícito e os pesos dos modelos |
