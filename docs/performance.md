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

## Memória

A renderização fica guardada depois da leitura barata só quando a página
pode escalar. O heap do Python fica em poucos megabytes e não cresce com o
número de páginas; `doc_id_for` lê o arquivo em blocos, e um documento
grande não fica residente antes de ser aberto.

O `tracemalloc` não vê a memória nativa do motor nem o alocador. Num serviço em
Linux que lê em várias threads, o glibc dá uma arena a cada thread, e cada arena
guarda os blocos grandes de pixels já liberados: a memória do processo sobe a
cada lote e não volta. `MALLOC_ARENA_MAX=2` no ambiente limita as arenas.
