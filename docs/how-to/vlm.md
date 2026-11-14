# Ligar um modelo de visão e linguagem

Este guia põe um modelo de visão e linguagem como leitor caro, servido na sua
máquina ou por um provedor. O leitor é `VLM`, do extra `vlm`. Ele fala com o
servidor pela biblioteca padrão do Python, no formato de chat da OpenAI com a
imagem embutida em base64. Qualquer servidor que fale esse formato serve.

Antes, ligue a escalada com um motor de reconhecimento óptico de caracteres
(OCR), como em
[Escalar só o que falhou](escalate.md). O modelo entra no mesmo lugar, em
`strong=`.

## Escolher o servidor

| servidor | comando | `VLM(...)` |
|---|---|---|
| llama.cpp | `llama-server -m model.gguf --mmproj mmproj.gguf --port 8089 -np 4 -c 32768` | `VLM(layout=PPDocLayout(), concurrency=4)` |
| vLLM | `vllm serve <modelo>` | `VLM("http://127.0.0.1:8000", "generic", layout=PPDocLayout())` |
| SGLang | `python -m sglang.launch_server --model-path <modelo> --port 30000` | `VLM("http://127.0.0.1:30000", "generic", layout=PPDocLayout())` |
| serviço de um provedor | o do provedor | `VLM(url, "generic", served=..., api_key=...)` e `allow_external=True` em `process()` |

O segundo argumento de `VLM` escolhe o preset, isto é, os prompts:

| preset | para |
|---|---|
| `"glm-ocr"` | o GLM-OCR, o padrão |
| `"paddleocr-vl"` | o PaddleOCR-VL-1.6 |
| `"generic"` | qualquer outro modelo, com um prompt de transcrição em português |

## Servir um modelo na sua máquina

Os dois modelos locais foram treinados sobre recortes de região. Por isso o
leitor recebe o detector de layout `PPDocLayout`, do extra `layout`. O
detector divide a página em regiões com rótulo, caixa e ordem de leitura.
Descarta cabeçalho, rodapé, carimbo e tarja pela estrutura da página, e lê
uma vez só a região que está dentro de outra. Sem o detector, o modelo recebe
a página inteira e inventa mais texto.

=== "uv"

    ```bash
    uv add "docaudit[ppocr,vlm,layout] @ git+https://github.com/hugohonda/docaudit"
    ```

=== "pip"

    ```bash
    pip install "docaudit[ppocr,vlm,layout] @ git+https://github.com/hugohonda/docaudit"
    ```

Instale o llama.cpp: `brew install llama.cpp` no macOS, ou a versão publicada
no GitHub do projeto, no Linux. Depois baixe os pesos e suba o servidor.

=== "GLM-OCR"

    ```bash
    D=~/.cache/docaudit/models/glm-ocr && mkdir -p $D
    curl -L -o $D/model.gguf  https://huggingface.co/ggml-org/GLM-OCR-GGUF/resolve/main/GLM-OCR-Q8_0.gguf
    curl -L -o $D/mmproj.gguf https://huggingface.co/ggml-org/GLM-OCR-GGUF/resolve/main/mmproj-GLM-OCR-Q8_0.gguf
    llama-server -m $D/model.gguf --mmproj $D/mmproj.gguf --port 8089 --host 127.0.0.1 -ngl 99 --temp 0 -np 4 \
      -c 32768 --flash-attn off --image-max-tokens 1024
    ```

=== "PaddleOCR-VL-1.6"

    ```bash
    D=~/.cache/docaudit/models/paddleocr-vl-1.6 && mkdir -p $D
    curl -L -o $D/model.gguf  https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF/resolve/main/PaddleOCR-VL-1.6-GGUF.gguf
    curl -L -o $D/mmproj.gguf https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF/resolve/main/PaddleOCR-VL-1.6-GGUF-mmproj.gguf
    shasum -a 256 $D/*.gguf
    # f3ae46ec885050acf4b3d31944431e1fd90d50664fb09126af4a3c050ba14ee8  model.gguf
    # 204d757d7610d9b3faab10d506d69e5b244e32bf765e2bab2d0167e65e0a058a  mmproj.gguf
    llama-server -m $D/model.gguf --mmproj $D/mmproj.gguf --port 8089 --host 127.0.0.1 -ngl 99 --temp 0 -np 4 \
      -c 32768
    ```

    Com este servidor, use `VLM(model="paddleocr-vl")`.

Três opções do servidor importam:

- `-np 4` atende quatro regiões de uma vez, o que `VLM(concurrency=4)` pede.
- `-c` fixa o contexto total, dividido entre as vagas de `-np`. Sem ele, cada
  vaga reserva o contexto inteiro do modelo, e o servidor pode ficar sem
  memória.
- `--image-max-tokens` limita os tokens de cada imagem. Sem ele, uma página
  inteira derruba o servidor do GLM-OCR.

Com o servidor no ar, passe o leitor em `strong=`:

```python
from docaudit import process
from docaudit.backends.layout import PPDocLayout
from docaudit.backends.vlm import VLM

reader = VLM(layout=PPDocLayout(), concurrency=4)
result = process("documento.pdf", policy="evidence", strong=reader)
```

Os pesos do detector baixam na primeira detecção, para
`~/.cache/docaudit/models`, conferidos pelo SHA-256.

Cada região vira um trecho com a caixa dela. Uma tabela chega num trecho só,
uma linha de texto por linha da tabela, com as células separadas por ` | `.
A linha da resposta sem letra latina nem dígito é descartada. Numa página
sem texto, o modelo repete uma frase em outro alfabeto.
Num servidor que serve mais de um modelo, diga qual com `served=`. Sem ele, o
leitor pergunta ao servidor qual é o único modelo servido.

O servidor em `127.0.0.1` não é externo: a página não sai da máquina.

## Usar o serviço de um provedor

A mesma classe fala com o serviço de um provedor que aceite o formato de chat
da OpenAI com imagem. A OpenAI, o Gemini, a Anthropic e o OpenRouter têm
um serviço assim. Use o preset `"generic"`.

!!! warning "A página sai da máquina"
    Um `url` cujo host não é a própria máquina torna o leitor externo.
    `process()` o recusa com `ExternalBackendError` até receber
    `allow_external=True`. Com essa autorização, cada página encaminhada vai
    ao provedor. Leia [Segurança dos dados](../security.md) antes de mandar
    um documento com dados pessoais.

```python
import os

from docaudit import process
from docaudit.backends.layout import PPDocLayout
from docaudit.backends.vlm import VLM

reader = VLM(
    "https://generativelanguage.googleapis.com/v1beta/openai",
    "generic",
    served="gemini-3-flash-preview",
    api_key=os.environ["GEMINI_API_KEY"],
    prices=(0.50, 3.00),
    reasoning="none",
    retries=3,
    layout=PPDocLayout(),
)
result = process(
    "documento-publico.pdf", policy="evidence", strong=reader, allow_external=True
)
print(result.spent.usd, result.spent.tokens_in, result.spent.tokens_out)
```

| parâmetro | para que serve |
|---|---|
| `served` | o nome do modelo no pedido; obrigatório fora da máquina |
| `api_key` | a credencial, enviada como `Bearer` |
| `prices` | dólares por milhão de tokens de entrada e de saída; sem ele, `spent.usd` fica `None` |
| `reasoning` | o esforço de raciocínio, enviado como `reasoning_effort` |
| `retries` | quantas vezes repetir uma chamada que falhou de passagem |

Um modelo que raciocina antes de responder gasta o raciocínio no mesmo teto
de `max_tokens`. `reasoning="none"` deixa o teto inteiro para a transcrição.
Os preços do exemplo são ilustrativos: a biblioteca não traz tabela de
preços, e quem chama informa os do provedor.

## Quando o servidor falha

Um erro do servidor falha a página, não o documento. A página fica com a
leitura barata, entra em `spent.pages_strong_failed` e emite um
`RuntimeWarning`. O mesmo vale para uma resposta que não se lê e para uma
resposta cortada no teto de `max_tokens`.

`retries=` repete a chamada antes de desistir da página, num servidor local
ou num externo:

| falha | com `retries=n` |
|---|---|
| HTTP 429 ou 5xx | repete até `n` vezes |
| `timeout` esgotado | repete até `n` vezes |
| conexão que caiu no meio | repete até `n` vezes |
| conexão recusada, servidor local | não repete: sobe `ConnectionError` e interrompe o documento |
| conexão recusada, servidor externo | repete até `n` vezes, como as outras |

A espera segue o `Retry-After` do servidor, ou dobra a cada tentativa a
partir de um segundo. O padrão, `retries=0`, não repete.

O servidor local ausente interrompe o documento porque as páginas seguintes
falhariam do mesmo jeito. Com `cache=ModelCallCache()`, a execução seguinte
retoma do que já foi lido. Os sintomas mais comuns, como o servidor que
responde 500 ou fica sem memória, estão em
[Problemas comuns](../troubleshooting.md). Os outros parâmetros de `VLM`
estão em [Configuração](../configuration.md).
