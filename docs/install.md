# Instalação

O pacote ainda não está no PyPI. A instalação é pelo repositório do GitHub,
com os extras de que você precisa.

## Requisitos

- Python 3.12, 3.13 ou 3.14.
- Linux em x86_64 ou aarch64, ou macOS com Apple Silicon.
- Rede na primeira leitura com o PP-OCR, para baixar os pesos. Depois, nada
  sai da máquina sem que você autorize.

O núcleo instala só pydantic, pypdfium2 e Pillow. Com ele você lê a
[camada de texto](glossary.md#camada-de-texto) de um PDF. Para ler uma
página [digitalizada](glossary.md#digitalizada), instale também um OCR.

## Instalar

=== "uv"

    ```bash
    uv add "docaudit[ppocr,openvino] @ git+https://github.com/hugohonda/docaudit"
    ```

=== "pip"

    ```bash
    pip install "docaudit[ppocr,openvino] @ git+https://github.com/hugohonda/docaudit"
    ```

Isso instala o PP-OCR, o OCR padrão, e o motor OpenVINO, que roda o mesmo
PP-OCR mais depressa na CPU.

Para fixar uma versão, acrescente o commit ou a tag ao fim da URL, como em
`git+https://github.com/hugohonda/docaudit@v0.1.0.dev1`. Uma tag publicada
não muda: ver [Versões e mudanças](changelog.md).

## Extras

Cada leitor é um extra. O nome do extra é o nome com que o leitor se
registra, e um motor alternativo leva o nome do motor.

| extra | traz | precisa também |
|---|---|---|
| `ppocr` | o PP-OCR em ONNX Runtime, o OCR padrão | nada; os pesos baixam na primeira leitura |
| `openvino` | o PP-OCR no OpenVINO, o motor padrão quando instalado | nada; traz o que o `ppocr` traz, salvo o ONNX Runtime |
| `tesseract` | o leitor `tesseract`, de outra família | o binário do Tesseract e o idioma `por` |
| `vlm` | nada: o leitor `vlm` fala com o servidor pela biblioteca padrão do Python | um servidor do modelo; ver [Ligar um modelo de visão e linguagem](how-to/vlm.md) |
| `layout` | o [detector de layout](glossary.md#detector-de-layout) `PPDocLayout` | nada; os pesos baixam na primeira detecção |
| `mojibake` | o sinal `MojibakeText`, que acha o texto decodificado com a codificação errada | nada |

Os extras se combinam: `docaudit[ppocr,openvino,tesseract,layout]`.

## Plataformas

| plataforma | núcleo e Tesseract | `ppocr` e `layout` | `openvino` | `engine="cuda"` |
|---|---|---|---|---|
| Linux x86_64 | sim | sim | sim | sim, com placa NVIDIA |
| Linux aarch64 | sim | sim | sim | não coberto |
| macOS com Apple Silicon | sim | sim | sim | não existe |
| macOS com Intel | não coberto | não coberto | não coberto | não existe |
| Windows | não coberto | não coberto | não coberto | não coberto |

"Não coberto" quer dizer que nenhum teste roda ali. Algumas dependências têm
wheel para essas plataformas, mas o pacote não promete nada nelas.

## O binário do Tesseract

O extra `tesseract` traz só o pacote Python. O motor é um programa do
sistema, e o idioma português é um pacote à parte.

=== "macOS"

    ```bash
    brew install tesseract tesseract-lang
    ```

=== "Debian ou Ubuntu"

    ```bash
    sudo apt-get install tesseract-ocr tesseract-ocr-por
    ```

`tesseract --list-langs` deve listar `por`. Outro idioma entra por
`TesseractOCR(lang=...)` ou pela variável `DOCAUDIT_OCR_LANG`.

## O motor do PP-OCR

O mesmo PP-OCR roda em três motores. Os pesos são os mesmos arquivos ONNX.

| motor | `engine=` | como instalar | quando usar |
|---|---|---|---|
| ONNX Runtime | `"onnxruntime"` | extra `ppocr` | o padrão sem o extra `openvino` |
| OpenVINO | `"openvino"` | extra `openvino` | na CPU; o padrão quando o extra está instalado |
| ONNX Runtime na GPU | `"cuda"` | `onnxruntime-gpu` no lugar do `onnxruntime` | com uma placa NVIDIA em Linux x86_64 |

Com `engine="auto"`, o padrão, o leitor usa o OpenVINO quando o extra está
instalado e o ONNX Runtime quando não está. O motor entra na
[chave do cache](glossary.md#cache), porque cada motor arredonda as caixas
de um jeito. Instalar o extra numa máquina troca o motor, e as leituras
guardadas com o outro deixam de servir. Quem fixa uma leitura em produção
passa `engine=` explícito.

### GPU

O `onnxruntime-gpu` e o `onnxruntime` ocupam o mesmo módulo Python e não
convivem no mesmo ambiente. Troque um pelo outro:

```bash
uv pip uninstall onnxruntime
uv pip install "onnxruntime-gpu[cuda,cudnn]"
```

O pacote do pip traz o CUDA e o cuDNN, sem instalação no sistema. Depois,
peça a GPU ao leitor:

```python
from docaudit.backends.ppocr import PPOCR

reader = PPOCR(engine="cuda")
```

O ONNX Runtime que não acha o CUDA passa para a CPU sem avisar. O leitor
confere a sessão e falha na primeira leitura, em vez de ler na CPU com o
nome da GPU: ver [Problemas comuns](troubleshooting.md#a-gpu-pedida-nao-e-usada).

!!! warning "Não suba o teto do OpenCV em ARM64"
    Em ARM64, os extras `ppocr` e `openvino` prendem o OpenCV abaixo de 4.14.
    O `resize` das versões 4.14 e 5.0 lê além do fim da imagem, e o processo
    cai com sinal 11. O teto sai quando o OpenCV trouxer a correção. Não
    instale outra versão à mão por cima dele.

## Conferir a instalação

```bash
python -c "import docaudit; print(docaudit.__version__)"
```

A versão sai da tag do git. Para baixar os pesos do
PP-OCR antes da primeira página, chame `prepare()`:

```pycon
>>> from docaudit.backends.ppocr import PPOCR
>>> reader = PPOCR()
>>> reader.prepare()
>>> reader.output_version
'3:PP-OCRv5_mobile_det+latin_PP-OCRv5_mobile_rec:rapidocr=<versão>:openvino'
```

O fim de `output_version` diz o motor em uso. Os pesos ficam em
`~/.cache/docaudit/models`, ou em `<DOCAUDIT_CACHE_DIR>/models` quando a
variável existe.

Com o pacote instalado, siga para a [primeira leitura](tutorial.md).
