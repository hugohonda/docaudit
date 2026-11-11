# Implantar num serviço

Este guia monta a biblioteca num serviço que lê documentos sem parar. Diz o
que preparar na imagem, onde guardar o cache, como dividir a CPU e o que muda
em cada plataforma. O custo de cada etapa, que explica estas escolhas, está em
[Desempenho](../performance.md).

## Em qualquer plataforma

- Baixe os pesos antes da primeira página. `PPOCR().prepare()` baixa os
  arquivos e abre as sessões do motor. Chame-o na construção da imagem e no
  início do processo. Assim a leitura não depende da rede. Um arquivo que
  falta falha antes do documento, e não página a página.
- Guarde as leituras num cache com caminho explícito,
  `ModelCallCache(path)`, num volume. Não monte o volume sobre
  `DOCAUDIT_CACHE_DIR`: ali ficam também os pesos baixados, e um volume vazio
  os esconderia.
- Fixe o motor com `PPOCR(engine=...)`. Com o padrão, `"auto"`, instalar o
  extra `openvino` troca o motor, e com ele a chave do cache, sem aviso.

```python
from docaudit import ModelCallCache, process
from docaudit.backends.ppocr import PPOCR

ocr = PPOCR(engine="openvino", threads=4)
ocr.prepare()  # pesos e sessões antes da primeira página
cache = ModelCallCache("/var/cache/docaudit-calls/calls.sqlite")

result = process("documento.pdf", cheap=["text_layer", ocr], cache=cache)
```

## Dividir a CPU

O PP-OCR faz uma inferência por vez em cada processo e já usa vários núcleos
dentro dela. Para ler mais depressa, rode mais processos, não mais threads:

- `PPOCR(threads=n)` fixa os núcleos de cada processo. Com vários processos,
  divida os núcleos entre eles. A receita
  [Ler muitos processos em lote](../recipes/batch.md) mostra o pool.
- `threads=None`, o padrão, usa todos os núcleos que o processo pode usar,
  inclusive o `cpuset` de um contêiner.
- A cota de CPU de um contêiner sem `cpuset` não aparece para o processo.
  Nesse caso, passe o número de vCPUs em `threads=`.

`process(workers=n)` distribui as páginas da etapa barata em threads, uma
tarefa por página. Só rende com um motor que solta o GIL fora do lock do PDF,
como o Tesseract, e com um leitor externo, que passa o tempo esperando a
rede. Com o PP-OCR e com a camada de texto, `workers` acima de um não ganha
nada. A saída é a mesma com qualquer número de workers.

Um leitor `vlm` local lê uma página por vez. O paralelismo dele é entre as
regiões da página: `VLM(concurrency=4)` com `llama-server -np 4`.

## Por plataforma

=== "Linux em contêiner"

    - Instale o extra `openvino`. Na CPU, o OpenVINO roda os mesmos arquivos
      ONNX mais depressa que o ONNX Runtime, com o mesmo texto. O motor entra
      em `output_version`, e a leitura de um não serve pelo outro no cache.
    - Passe em `threads=` o número de vCPUs do contêiner. Acima disso, o motor
      disputa núcleos que não tem.
    - Ponha `MALLOC_ARENA_MAX=2` no ambiente. Veja [Memória](#memoria).
    - Não baixe o DPI para ganhar tempo. Numa página densa, o reconhecimento
      das linhas leva a maior parte do tempo, e o DPI quase não o muda.

    Um `Dockerfile` de referência, para CPU. A versão é um commit. O `tar.gz`
    do GitHub traz a versão no `.git_archival.txt`, sem precisar do `git` na
    imagem:

    ```dockerfile
    FROM python:3.13-slim
    ENV MALLOC_ARENA_MAX=2
    RUN pip install --no-cache-dir \
        "docaudit[ppocr,openvino] @ https://github.com/hugohonda/docaudit/archive/<commit>.tar.gz"
    # Os pesos entram na imagem: a primeira leitura não depende da rede.
    RUN python -c "from docaudit.backends.ppocr import PPOCR; PPOCR(engine='openvino').prepare()"
    VOLUME /var/cache/docaudit-calls
    ```

    No serviço, use `ModelCallCache("/var/cache/docaudit-calls/calls.sqlite")`
    e `PPOCR(engine="openvino", threads=<vCPUs>)`.

=== "macOS com Apple Silicon"

    - O extra `openvino` também rende na CPU do Mac, com o mesmo texto do ONNX
      Runtime.
    - Não ponha `MALLOC_ARENA_MAX`: o alocador do macOS não tem arenas por
      thread.

    !!! warning "Não suba o teto do OpenCV"
        O pacote prende o OpenCV abaixo da versão 4.14 em ARM64. O `resize`
        das versões 4.14 e 5.0 lê além do fim da imagem e derruba o processo
        com o sinal 11. Não troque essa versão à mão.

=== "GPU"

    - Use `PPOCR(engine="cuda")`, com o `onnxruntime-gpu` no lugar do
      `onnxruntime`. A instalação está em [Instalação](../install.md).
    - Rode poucos processos que dividem a placa. A CPU de cada um renderiza e
      recorta enquanto a placa reconhece. `threads=` continua dividindo a CPU
      entre eles.
    - A detecção roda na resolução da página, e uma digitalização grande pede
      memória da placa. A página que falha por falta dela não some. A decisão dela traz a mensagem
      do ONNX Runtime em `failures`, e `incomplete` diz que nenhum outro leitor
      leu no lugar.
    - Sem o CUDA, o ONNX Runtime leria na CPU sem avisar. O leitor confere a
      sessão e falha na primeira leitura.

## Memória

A renderização da página fica guardada depois da leitura barata só quando a
página pode escalar. A memória do Python não cresce com o número de páginas,
e o arquivo é lido em blocos para calcular o `doc_id`.

O `tracemalloc` não vê a memória nativa do motor nem a do alocador. Num
serviço em Linux que lê em várias threads, o glibc dá uma arena a cada
thread. Cada arena guarda os blocos grandes de pixels já liberados, e a
memória do processo sobe a cada lote e não volta. `MALLOC_ARENA_MAX=2` no
ambiente limita as arenas.

## Antes de pôr no ar

- Os pesos estão na imagem, com `prepare()` no build.
- O cache tem caminho explícito, num volume que não é `DOCAUDIT_CACHE_DIR`.
- `engine=` está fixo.
- `threads=` divide os núcleos entre os processos.
- `MALLOC_ARENA_MAX=2` está no ambiente, em Linux.
- Um leitor externo só entra com `allow_external=True` e depois de ler
  [Segurança dos dados](../security.md).
