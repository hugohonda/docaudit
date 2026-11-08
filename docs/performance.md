# Desempenho

O custo de cada etapa, em ordem de grandeza, e as escolhas de padrão que
vêm dele. Reproduza na sua máquina antes de usar um número como estimativa.

## Custo por etapa

Numa página A4 nato-digital de texto denso, em CPU: decidir o substrato custa
décimos de milissegundo; tirar as linhas de texto embutido com caixa, uns
poucos milissegundos; renderizar a 200 dpi, dezenas de milissegundos (o
dobro em RGB); o OCR da página inteira, centenas de milissegundos a segundos.
A triagem custa cerca de um quinze avos da renderização que evita e um
milésimo do OCR. As linhas custam o dobro dos retângulos crus do pdfium,
porque a caixa da linha une as dos glifos.

## Escolhas que vieram daí

**Uma renderização por página escalada.** A leitura barata, a releitura e a
leitura cara usam a mesma renderização, solta quando a página sai do
caminho. Um leitor que pede outro modo de cor paga a dele.

**Tons de cinza para o Tesseract.** Renderizar em cinza custa menos da
metade do RGB, e o Tesseract converte para cinza de qualquer forma. O PP-OCR
e o leitor caro pedem RGB, que é o formato para o qual os pesos deles foram feitos.

**TIFF no caminho do Tesseract.** O `pytesseract` grava um arquivo
temporário no formato que a imagem declara. Rotular a imagem como TIFF evita
recomprimir PNG, sem perda.

**Lock em vez de pool de processos.** O pdfium não é seguro para uso
concorrente. Numa execução com OCR, o lock fica tomado uma fração de um por
cento do tempo de parede: serializar só o pdfium custa menos que passar
páginas entre processos.

## Paralelismo

`workers` distribui as páginas baratas, uma tarefa por página. O ganho vem
do OCR que roda fora do lock do pdfium: com o Tesseract, quatro workers
leem cerca de três vezes mais depressa e oito cerca de cinco vezes. Uma
cascata que só lê a camada de texto não ganha nada. O PP-OCR roda uma
chamada por vez, porque o ONNX Runtime cai com chamadas simultâneas, e já
paraleliza dentro dela (`PPOCR(threads=)`). A saída é idêntica em qualquer
número de workers.

No tier caro, `workers` só vale para um leitor hospedado (`external`), que
espera a rede. Um modelo local vai página a página, e o paralelismo dele é
entre regiões: `VLM(concurrency=4)` com `llama-server -np 4`.

## Leitores

Ordem de grandeza por página, de condições diferentes (threads, conjunto,
servidor):

| leitor | por página |
|---|---|
| Tesseract 5.5, `por` | décimos de segundo |
| PP-OCRv5 latino (ONNX, CPU), o padrão | cerca de um segundo |
| PP-OCRv6 medium | cerca de três segundos |
| GLM-OCR, por região | cinco a doze segundos |

O PP-OCRv5 é o padrão pelo custo. O `v6-medium` custa cerca de quatro vezes mais. Na CPU,
o OpenVINO roda os mesmos arquivos mais rápido que o ONNX Runtime.

`strong=` não tem padrão, porque o leitor caro certo depende do documento e do orçamento.
A densidade da página não é sinal para escalar: um modelo de visão e linguagem custa mais,
e na folha inteira tende a perder valores em página densa. Compare nos seus documentos. Para quem queira um, o GLM-OCR por região: ver
[Começando](getting-started.md) para o servidor.

## DPI por página

Uma página escaneada é renderizada na resolução nativa do raster dela, presa
a [150, 300]. Em páginas escaneadas, a resolução nativa custou um quinto
menos que 200 dpi para todas, com a mesma leitura.

## Seleção de páginas

`pages=` restringe o processamento, e as páginas de fora não chegam a ser
carregadas: a triagem custa por página carregada, não por página do
documento.

## Tempo por página

`RoutingDecision.seconds` traz, por página, os segundos de cada etapa que a
tocou. Uma página densa que custa muito mais que as vizinhas na etapa barata
aponta para o reconhecedor; a mesma diferença em `strong` aponta para o
leitor caro ou para a rede.

## Memória

A renderização fica guardada depois da leitura barata só quando a página
pode escalar. O heap do Python fica em poucos megabytes e não cresce com o
número de páginas; `doc_id_for` lê o arquivo em blocos, e um documento
grande não fica residente antes de ser aberto.

O `tracemalloc` não vê a memória nativa do motor nem o alocador. Num serviço em
Linux que lê em várias threads, o glibc dá uma arena a cada thread, e cada arena
guarda os blocos grandes de pixels já liberados: a memória do processo sobe a
cada lote e não volta. `MALLOC_ARENA_MAX=2` no ambiente limita as arenas.

## Implantação

As regras abaixo vêm das medições de serviço e de laptop. O número de cada
uma muda com a máquina; a regra e o porquê ficam.

**Em qualquer plataforma.**

- `PPOCR.prepare()` na construção da imagem ou no início do processo: baixa
  os pesos e abre as sessões antes da primeira página, e a leitura não
  depende da rede. O detector de layout baixa na primeira detecção, para
  `<DOCAUDIT_CACHE_DIR>/models`.
- Um cache de leituras com caminho explícito, `ModelCallCache(path)`, num
  volume. Não monte um volume sobre `DOCAUDIT_CACHE_DIR`: é onde ficam
  também os pesos baixados, e o volume vazio os esconderia.
- Uma inferência do PP-OCR por vez em cada processo. Para ler mais depressa,
  mais processos, não mais threads: `threads=` divide os núcleos entre eles
  ([Lote](recipes.md#lote-de-muitos-autos)).
- Um leitor hospedado espera a rede: `workers` acima de um só rende nele e no
  Tesseract.

**Linux em contêiner, CPU.**

- O extra `openvino`: o PP-OCR lê os mesmos arquivos várias vezes mais
  depressa que no ONNX Runtime, com o mesmo texto; o motor entra em
  `output_version`, e as leituras de um não servem pelo outro.
- `threads=` igual ao número de vCPUs do contêiner. Acima disso o motor
  disputa núcleos que não tem.
- `MALLOC_ARENA_MAX=2` no ambiente. O glibc dá uma arena a cada thread e
  guarda nela os blocos grandes de pixels já liberados; sem o limite, a
  memória do processo sobe a cada lote e não volta ([Memória](#memoria)).
- O reconhecimento é a maior parte do tempo numa página densa; o DPI quase
  não o muda. Baixar o DPI não compensa a perda de leitura.

Um `Dockerfile` de referência, para CPU. A versão é um commit; o `tar.gz` do
GitHub traz a versão pelo `.git_archival.txt`, sem precisar do `git` na
imagem:

```dockerfile
FROM python:3.13-slim
ENV MALLOC_ARENA_MAX=2
RUN pip install --no-cache-dir \
    "docaudit[ppocr,openvino] @ https://github.com/hugohonda/docaudit/archive/<commit>.tar.gz"
# Os pesos entram na imagem: a primeira leitura não depende da rede.
RUN python -c "from docaudit.backends.ppocr import PPOCR; PPOCR().prepare()"
VOLUME /var/cache/docaudit-calls
```

No serviço, `ModelCallCache("/var/cache/docaudit-calls/calls.sqlite")` e
`PPOCR(threads=<vCPUs>)`.

**macOS com Apple Silicon.**

- O extra `openvino` também rende na CPU do Mac, com o mesmo texto do ONNX
  Runtime.
- O OpenCV fica abaixo de 4.14 em ARM64, pelo `pyproject` do pacote: o
  `resize` das versões 4.14 e 5.0 lê além da imagem e derruba o processo.
  Não suba o teto à mão.
- Sem `MALLOC_ARENA_MAX`: o alocador do macOS não tem arenas por thread.

**GPU.**

- `PPOCR(engine="cuda")` com o `onnxruntime-gpu` no lugar do `onnxruntime`,
  em poucos processos que partilham a placa; a CPU de cada um renderiza e
  recorta enquanto a placa reconhece. A detecção roda na resolução da página,
  e a digitalização grande pede memória da placa: a página que falha por
  falta dela fica em `failures` da decisão, com `incomplete`.
- Um leitor `vlm` local vai página a página, e o paralelismo dele é entre
  regiões: `VLM(concurrency=4)` com `llama-server -np 4`.
