# Problemas comuns

Cada título é o sintoma. Abaixo dele vêm a causa e o que fazer.

## O servidor `vlm` responde 500 ou 429

O `llama-server` rejeita a própria saída com um 500 numa parte das chamadas.
Um serviço [externo](glossary.md#externo) responde 429 quando você passa do
limite de uso. Nos dois casos, a página encaminhada entra em
`spent.pages_strong_failed`, e `process` emite um `RuntimeWarning`. Ela
fica com a leitura barata numa política que decide depois da leitura
barata, como `evidence`. O documento segue.

Peça ao leitor que repita a chamada:

```python
from docaudit.backends.layout import PPDocLayout
from docaudit.backends.vlm import VLM

reader = VLM(layout=PPDocLayout(), concurrency=4, retries=3)
```

`retries=` repete o 429, o 5xx, o tempo esgotado e a conexão que caiu, num
servidor local ou externo. A espera segue o `Retry-After` do servidor, ou
dobra a cada tentativa. Com `cache=`, uma segunda execução lê do disco o que
já foi lido e chama o servidor só para o resto. Ver
[Ligar um modelo de visão e linguagem](how-to/vlm.md).

## O documento para com `ConnectionError`

Nenhum servidor respondeu no endereço de um leitor `vlm` local. Repetir não
traz o servidor de volta, e por isso o documento para, em vez de falhar
página a página. Suba o servidor e confira a porta em `VLM(url=...)`.

Num servidor externo, a conexão recusada conta como falha passageira da
página: é repetida `retries` vezes, e depois a página fica com a leitura
barata.

## O servidor do modelo cai por falta de memória

O `llama-server` sem `-c` reserva o contexto inteiro do modelo para cada
vaga de `-np`. Com quatro vagas, isso pode passar da memória da máquina. Sem
`--image-max-tokens`, a imagem de uma página inteira gera tokens demais, e o
servidor do GLM-OCR cai.

Passe os dois ao servidor, e faça `-np` igual ao `concurrency` do leitor:

```bash
llama-server -m model.gguf --mmproj mmproj.gguf --port 8089 --host 127.0.0.1 \
  -ngl 99 --temp 0 -np 4 -c 32768 --flash-attn off --image-max-tokens 1024
```

`-c` é o contexto total, dividido entre as vagas. O detector de layout
(`VLM(layout=PPDocLayout())`) também ajuda: cada chamada leva uma região, e
não a página inteira.

## `process` levanta `ExternalBackendError`

Um dos leitores declara que envia a página para fora da máquina, e a chamada
não autorizou. A recusa vem antes de abrir o documento, e nenhuma página saiu.

Um `VLM(url=...)` cujo host não é a própria máquina é externo. Se é isso que
você quer, autorize:

```python
import docaudit

result = docaudit.process("documento.pdf", strong=reader, allow_external=True)
```

Se o servidor roda na sua máquina, use `127.0.0.1` ou `localhost` na URL. O
que sai e o que fica estão em [Segurança dos dados](security.md).

## `process` levanta `DocumentError`

O pdfium não abriu o arquivo. A mensagem diz qual dos dois casos:

| mensagem | causa | o que fazer |
|---|---|---|
| `o PDF está protegido por senha` | o arquivo pede senha | tire a senha antes, com a ferramenta que a conhece |
| `o arquivo não é um PDF legível` | arquivo truncado, outro formato, ou PDF sem página | confira o arquivo; uma imagem precisa ser PNG, JPEG, TIFF, BMP ou WebP |

## A GPU pedida não é usada

O ONNX Runtime que não acha o CUDA cria a sessão na CPU sem avisar. Para não
ler na CPU com o nome da GPU, `PPOCR(engine="cuda")` confere a sessão e falha
na primeira leitura:

```text
PP-OCR: engine='cuda' sem o provedor CUDA do ONNX Runtime (sessão com ['CPUExecutionProvider']); instale onnxruntime-gpu no lugar de onnxruntime
```

A causa comum é o `onnxruntime` instalado junto do `onnxruntime-gpu`. Os dois
ocupam o mesmo módulo, e o de CPU vence. Troque um pelo outro:

```bash
uv pip uninstall onnxruntime onnxruntime-gpu
uv pip install "onnxruntime-gpu[cuda,cudnn]"
```

Ver [Instalação](install.md#gpu).

## A decisão da página tem `incomplete`

Um leitor falhou na página, e nenhum outro leu no lugar dele. As linhas da
página, se houver, são só parte dela. `RoutingDecision.failures` traz cada
falha como `<leitor>: <mensagem>`.

```python
for decision in result.decisions:
    if decision.incomplete:
        print(decision.page, decision.failures)
```

Na GPU, a causa comum é a digitalização grande que pede mais memória da
placa do que há: a detecção roda na resolução da página. Um segundo leitor
na [cascata](glossary.md#cascata) lê a página quando o primeiro falha, e
então ela não fica incompleta. Quando só o leitor caro falhou, a página não
tem `incomplete`: a leitura barata fica, e a falha aparece em `failures`.

## A memória do processo sobe a cada lote e não volta

Num serviço em Linux que lê em várias threads, o glibc dá uma arena de
memória a cada thread. Cada arena guarda os blocos grandes de pixels já
liberados, e o processo não os devolve ao sistema. O `tracemalloc` não vê
essa memória, porque ela é do alocador e não do Python.

Limite as arenas no ambiente do processo:

```bash
export MALLOC_ARENA_MAX=2
```

No macOS isso não acontece: o alocador dele não tem arenas por thread. Ver
[Implantar num serviço](how-to/deploy.md).

## O cache para de servir depois de instalar o OpenVINO

Com `engine="auto"`, o padrão, o `PPOCR` usa o OpenVINO quando o extra está
instalado. O motor entra na `output_version` do leitor e, com ela, na chave
do [cache](glossary.md#cache). Instalar o extra troca o motor, e as leituras
guardadas com o ONNX Runtime deixam de servir.

Fixe o motor:

```python
from docaudit.backends.ppocr import PPOCR

reader = PPOCR(engine="onnxruntime")
```

`reader.output_version` termina com o motor em uso quando ele não é o
ONNX Runtime na CPU (`onnxruntime`). Quem compara execuções
pelo cache, ou fixa uma leitura em produção, passa `engine=` sempre.

## O processo cai com sinal 11 em ARM64

O `resize` do OpenCV 4.14 e 5.0 lê além do fim da imagem em ARM64, e o
processo cai sem traceback (`SIGSEGV`). Os extras `ppocr` e `openvino`
prendem o OpenCV abaixo de 4.14 nessa arquitetura, mas outro pacote do
ambiente pode trazer uma versão mais nova.

Confira a versão e o pacote que a trouxe:

```bash
python -c "import cv2; print(cv2.__version__)"
uv pip list | grep -i opencv
```

Se a versão for 4.14 ou mais nova, volte ao teto:

```bash
uv pip install "opencv-python-headless<4.14"
```

!!! warning "Não suba o teto do OpenCV"
    O teto sai do pacote quando o OpenCV trouxer a correção. Até lá, não
    instale uma versão mais nova à mão em ARM64.

## A camada de texto sai com letras trocadas

O texto extraído parece texto, mas com caracteres errados no lugar dos
acentos: `honor·rios` por `honorários`. A tabela de caracteres da fonte
(ToUnicode) do PDF está errada, e a camada foi decodificada com a codificação
trocada. O sinal `GarbledText` não pega esse caso, porque nenhum caractere é
de controle nem de substituição.

O sinal `MojibakeText` reconhece essa troca. Ele vem no extra `mojibake` e
fica fora de `DEFAULT_SIGNALS`:

```python
import docaudit
from docaudit.backends.ppocr import PPOCR
from docaudit.policies import DEFAULT_SIGNALS, EvidenceRouter, MojibakeText

result = docaudit.process(
    "documento.pdf",
    policy=EvidenceRouter([*DEFAULT_SIGNALS, MojibakeText()]),
    strong=PPOCR(),
)
```

Com um OCR em `strong=`, a página marcada vai a ele, que a lê pelos pixels
e não pela camada.
