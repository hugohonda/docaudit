# Começando

Três passos: instalar, ler um documento, inspecionar o resultado. Depois,
ligar um leitor caro.

## 1. Instalar

!!! warning "Ainda não publicado"
    Nada foi ao PyPI ainda, então `uv add docaudit` não resolve. Por enquanto a
    instalação é a partir do repositório.

```bash
uv add "docaudit[ppocr,openvino] @ git+https://github.com/hugohonda/docaudit"
```

Publicado, será `uv add 'docaudit[ppocr,openvino]'`.

Requer Python 3.12 a 3.14. Os extras `ppocr` e `layout` têm wheel para Linux
x86_64 e aarch64 e para macOS em Apple Silicon.

| extra | traz | precisa também |
|---|---|---|
| `ppocr` | o OCR padrão, PP-OCR em ONNX Runtime | nada; os pesos baixam na primeira leitura |
| `openvino` | o PP-OCR no OpenVINO, o motor padrão quando instalado | o extra `ppocr` |
| `tesseract` | o Tesseract, a alternativa rápida | o binário e o pacote `por` |
| `vlm` | nada: o leitor fala com o servidor pela biblioteca padrão | um servidor para o modelo |
| `layout` | o detector de layout `PPDocLayout` | nada; os pesos baixam na primeira detecção |

```bash
brew install tesseract tesseract-lang                 # macOS
sudo apt-get install tesseract-ocr tesseract-ocr-por  # Debian ou Ubuntu
```

## 2. Ler um documento

Sem nenhum argumento além do documento, `process` lê a camada de texto onde
houver e manda o resto ao PP-OCR. Nenhuma página escala.

```python
import docaudit

result = docaudit.process("documento.pdf")
```

Uma imagem também é um documento: PNG, JPEG, TIFF, BMP ou WebP vira um PDF de
uma página por quadro, no DPI que a imagem declara.

```python
result = docaudit.process("pagina.png")
```

## 3. Inspecionar o resultado

```python
for chunk in result.chunks[:5]:
    print(chunk.page, chunk.source, chunk.confidence, chunk.text[:60])

print(result.pages[0].substrate)  # born_digital, searchable_scan ou image_only
print(result.spent)
```

Cada trecho carrega de onde veio. A caixa é normalizada; para recortar a
imagem, converta com o tamanho dela:

```python
>>> c = result.chunks[0]
>>> c.page, c.source, c.reading_order, c.confidence
(0, 'text_layer', 0, None)
>>> c.bbox.to_pixels(1653, 2339)
(828, 210, 1426, 239)
```

Três saídas prontas:

```python
result.to_markdown()  # texto por página, para busca ou para um modelo
result.model_dump_json()  # tudo; Result.model_json_schema() descreve o formato
```

Para conferir a olho, `visualize` devolve a imagem de cada página com a
caixa de cada linha na cor do leitor que a leu. A linha cujo valor ainda
falha uma verificação, como um erro impresso no documento, ganha um contorno
preto. A legenda fica numa faixa acima da página:

```python
from docaudit import visualize

images = visualize(result, "documento.pdf", pages=[0], show_order=True)
images[0].save("pagina-0.png")
```

Os passos que `process` deu em cada página estão em `result.decisions`, e os
campos de cada objeto, em [Formato da resposta](response.md).

## Conferir a leitura e escalar só o que falhou

O leitor caro é um `Reader` como os baratos. Aqui o tier barato é o padrão, e
a escalada vai a um PP-OCR maior:

```python
from docaudit import Budget
from docaudit.backends.ppocr import PPOCR

result = docaudit.process(
    "documento.pdf",
    policy="evidence",
    strong=PPOCR("v6-medium"),
    budget=Budget(max_strong_pages=10),
)
for d in result.decisions:
    if d.reason != "sem evidência de falha":
        print(d.page, d.tier, d.reason)  # por que a página foi encaminhada
```

`evidence` lê tudo no tier barato primeiro e encaminha só a página cuja
leitura falhou numa verificação. O leitor caro relê a página, e a linha dele
entra só onde conserta o valor sem perder outro. Sem evidência, nada escala.
`confirm=TesseractOCR()` relê antes com outra família, para separar o erro
impresso no documento do erro de leitura: ver
[Conceitos](concepts.md). `Budget` é um teto opcional em páginas. Sem `strong=`,
nenhuma página escala, qualquer que seja a política.

### Um modelo de visão e linguagem

`VLM` lê a página por um modelo de visão e linguagem servido pelo llama.cpp,
ou por qualquer servidor compatível com a API da OpenAI, como vLLM e SGLang:
ver [Configuração](configuration.md#servidores-para-o-leitor-vlm).
Os presets locais são `glm-ocr` (GLM-OCR), o padrão, e `paddleocr-vl`
(PaddleOCR-VL-1.6); o
`generic` serve a um modelo hospedado. Os dois modelos locais foram treinados sobre
recortes de região, e por isso o leitor vem com um detector de layout,
`PPDocLayout`, que recorta a página em regiões com rótulo, caixa e ordem de
leitura e descarta cabeçalho, rodapé, carimbo e tarja por estrutura. Uma
região dentro de outra é lida uma vez só. Sem o detector, o modelo recebe a
folha inteira e alucina mais.

```bash
uv add "docaudit[ppocr,vlm,layout] @ git+https://github.com/hugohonda/docaudit"
brew install llama.cpp   # ou a release do GitHub, em Linux

# GLM-OCR, com `--flash-attn off` e um teto de tokens por imagem
D=~/.cache/docaudit/models/glm-ocr && mkdir -p $D
curl -L -o $D/model.gguf  https://huggingface.co/ggml-org/GLM-OCR-GGUF/resolve/main/GLM-OCR-Q8_0.gguf
curl -L -o $D/mmproj.gguf https://huggingface.co/ggml-org/GLM-OCR-GGUF/resolve/main/mmproj-GLM-OCR-Q8_0.gguf
llama-server -m $D/model.gguf --mmproj $D/mmproj.gguf --port 8089 --host 127.0.0.1 -ngl 99 --temp 0 -np 4 \
  -c 32768 --flash-attn off --image-max-tokens 1024

# PaddleOCR-VL-1.6: o mesmo servidor, outros pesos; VLM(model="paddleocr-vl")
D=~/.cache/docaudit/models/paddleocr-vl-1.6 && mkdir -p $D
curl -L -o $D/model.gguf  https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF/resolve/main/PaddleOCR-VL-1.6-GGUF.gguf
curl -L -o $D/mmproj.gguf https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF/resolve/main/PaddleOCR-VL-1.6-GGUF-mmproj.gguf
shasum -a 256 $D/*.gguf
# f3ae46ec885050acf4b3d31944431e1fd90d50664fb09126af4a3c050ba14ee8  model.gguf
# 204d757d7610d9b3faab10d506d69e5b244e32bf765e2bab2d0167e65e0a058a  mmproj.gguf
llama-server -m $D/model.gguf --mmproj $D/mmproj.gguf --port 8089 --host 127.0.0.1 -ngl 99 --temp 0 -np 4 \
  -c 32768
```

`-np 4` deixa o servidor atender quatro regiões de uma vez, que é o que
`concurrency=4` pede, e `-c 32768` dá 8.192 tokens a cada uma. Sem `-c`,
cada vaga reserva o contexto inteiro do modelo, e o servidor pode falhar
por memória. Sem `--image-max-tokens`, uma folha inteira a 200 dpi
derruba o servidor do GLM-OCR. Os pesos do detector baixam na primeira
detecção, para `~/.cache/docaudit/models`, conferidos pelo SHA-256.

```python
from docaudit.backends.layout import PPDocLayout
from docaudit.backends.vlm import VLM

reader = VLM(layout=PPDocLayout(), concurrency=4)
result = docaudit.process("documento.pdf", policy="evidence", strong=reader)
```

Cada região vira um chunk com a caixa dela. Uma tabela chega num chunk só,
uma linha de texto por linha da tabela, com as células separadas por ` | `.

O servidor na própria máquina não é externo. Apontar `VLM(url=...)` para
outra máquina torna o leitor externo, e `process()` passa a exigir
`allow_external=True`.

### Um modelo hospedado

A mesma classe fala com qualquer endpoint no formato de chat da OpenAI com
imagem embutida: o da OpenAI, o compatível do Gemini, o da Anthropic, o
OpenRouter. O preset `generic` traz um prompt de transcrição em português;
`served` nomeia o modelo no pedido; `prices` é o que faz `spent.usd`
existir, em dólares por milhão de tokens de entrada e de saída. O host não é a
própria máquina, então o leitor é externo e `process()` exige
`allow_external=True`: a página sai da máquina. Um modelo que pensa antes de
responder, como o Gemini 3, gasta o pensamento no mesmo teto de
`max_tokens`; `reasoning="none"` deixa o teto para a transcrição.

```python
import os

reader = VLM(
    "https://generativelanguage.googleapis.com/v1beta/openai",
    "generic",
    served="gemini-3-flash-preview",
    api_key=os.environ["GEMINI_API_KEY"],
    prices=(0.50, 3.00),
    reasoning="none",
    layout=PPDocLayout(),
)
result = docaudit.process(
    "documento-publico.pdf", policy="evidence", strong=reader, allow_external=True
)
print(result.spent.usd, result.spent.tokens_in, result.spent.tokens_out)
```

### Quando o servidor falha

Um erro do servidor, local ou hospedado, falha a página inteira. O
`llama-server` rejeita a própria saída com um 500 numa fração das chamadas, e
um servidor hospedado responde 429 ao limite de uso. A página fica com a
leitura barata, quando houve, entra em `spent.pages_strong_failed` e emite um
`RuntimeWarning`. O mesmo vale para o tempo esgotado esperando a resposta e
para uma resposta que não se lê. Só um servidor ausente interrompe o
processamento. Quanto esperar e quantas vezes repetir é de quem chama. Com `cache`, a execução
seguinte retoma do que já foi lido.

## Para um agente: ler, duvidar, reler um recorte

`Document` guarda o documento aberto, os leitores e o cache entre chamadas.
Com ele, uma pessoa ou um agente lê, lista as linhas cujo valor não confere,
relê só um recorte com o leitor que escolher e vê a imagem dele. O que
entregar a um modelo, em que ordem e como conferir a citação está em
[Análise por um agente](agent.md); o exemplo com `Document`, em
[Receitas](recipes.md#um-agente-que-confere-o-que-leu).

## Próximos passos

- [Conceitos](concepts.md): o que a biblioteca decide por você e por quê.
- [Configuração](configuration.md): cada argumento, os leitores e os servidores.
- [Receitas](recipes.md): casos completos.
- [Limites](limits.md): onde ela falha.
