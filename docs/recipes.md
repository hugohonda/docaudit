# Receitas

Casos de uso completos. Cada um parte do mínimo que funciona e diz o que
mudar para o seu acervo.

## Uma relação de nome e valor digitalizada

A relação de pagamentos de um diário oficial, ou o anexo de um edital, é uma
tabela longa de nome, id e valor, muitas vezes digitalizada. O tier barato lê todas as páginas. Só a página em que um valor
em reais ou um CPF não confere vai ao leitor por região, que devolve cada
tabela num trecho, uma linha de texto por linha da tabela.

```python
import docaudit
from docaudit import Budget
from docaudit.backends.layout import PPDocLayout
from docaudit.backends.vlm import VLM
from docaudit import ModelCallCache
from docaudit.policies import AMOUNT_BRL, fold_lookalikes

result = docaudit.process(
    "edital.pdf",
    policy="evidence",
    budget=Budget(max_strong_fraction=0.1),
    strong=VLM(layout=PPDocLayout(), concurrency=4),
    cache=ModelCallCache(),
)

for chunk in result.chunks:
    if chunk.kind != "table":
        continue
    for line in chunk.text.splitlines():
        cells = [cell.strip() for cell in line.split(" | ")]
        amounts = [m.group(0) for m in AMOUNT_BRL.pattern.finditer(fold_lookalikes(line))]
        print(chunk.page, cells, amounts)
```

`chunk.kind == "table"` só aparece nos trechos do leitor por região. Nas
páginas que ficaram no tier barato, a tabela chega linha a linha, sem
separador de célula. Um valor que quebra entre duas linhas fica partido entre
dois trechos; ver [Limites](limits.md).

## Diário oficial em duas colunas

Um OCR por linha devolve as linhas pela altura, e numa folha em duas colunas
isso intercala as colunas. O detector de layout põe cada linha no bloco que a
contém e devolve os blocos na ordem de leitura.

```python
import docaudit
from docaudit.backends.layout import PPDocLayout

result = docaudit.process("diario.pdf", layout=PPDocLayout(drop=()))
print(result.to_markdown())
```

O porquê de `drop=()` está em
[Configuração](configuration.md#ppdoclayout). Cada linha ganha o rótulo do bloco em
`Chunk.kind`. O tempo da detecção está em [Desempenho](performance.md#leitores).

## Mascarar CPF na imagem pela caixa

A caixa de cada trecho permite cobrir na imagem a linha que traz um CPF. A
caixa é da linha inteira, não só dos dígitos.

```python
import io

from PIL import Image, ImageDraw

import docaudit
from docaudit.pdf import opened, render_of
from docaudit.policies import CPF, fold_lookalikes

result = docaudit.process("relatorio.pdf", cheap=["text_layer"])
page = result.pages[0]
with opened("relatorio.pdf") as handle:
    png = render_of(handle, page.index, dpi=page.dimensions.dpi)
image = Image.open(io.BytesIO(png)).convert("RGB")

draw = ImageDraw.Draw(image)
for chunk in result.by_page()[page.index]:
    if CPF.pattern.search(fold_lookalikes(chunk.text)):
        draw.rectangle(chunk.bbox.to_pixels(image.width, image.height), fill="black")
image.save("relatorio-p0-mascarado.png")
```

Um CPF que o leitor não leu fica sem máscara. Para uma folha digitalizada, a
máscara só cobre o que o OCR achou.

## Um agente que confere o que leu

A decisão automática já existe: `process(..., confirm=TesseractOCR())` relê
com outra família a linha que falhou, deixa como erro do documento o mesmo
valor inválido e troca a linha quando um valor que confere aparece no mesmo
lugar. `Document` serve quando quem decide é uma pessoa ou um agente: ele
lista as linhas cujo valor não confere, relê só o recorte com o leitor que
quem decide escolher, e entrega a imagem do recorte.

```python
from pathlib import Path

from docaudit import Document
from docaudit.backends.ppocr import PPOCR
from docaudit.backends.tesseract import TesseractOCR
from docaudit import ModelCallCache

cache = ModelCallCache(Path(".cache/docaudit.sqlite"))
Path("revisao").mkdir(exist_ok=True)

with Document("autos.pdf", cheap=["text_layer", PPOCR()], cache=cache) as doc:
    result = doc.read()  # política evidence por padrão
    for n, doubt in enumerate(doc.doubts(result)):
        again = doc.reread(doubt.chunk.page, doubt.chunk.bbox, TesseractOCR())
        print(doubt.chunk.page, doubt.check, doubt.value)
        print("  lido de novo:", " / ".join(c.text for c in again))
        png = doc.crop(doubt.chunk.page, doubt.chunk.bbox)
        Path(f"revisao/{n}-p{doubt.chunk.page}.png").write_bytes(png)
```

`doubts` lista o que os sinais da política apontam por linha: o valor que
falha, só em linha escrita por um motor, e o caractere de decodificação
quebrada, em qualquer linha; o que cada um prova está na docstring de
`Document.doubts`. Para entregar a leitura a um modelo, com cada conclusão
presa à linha, ver [Análise por um agente](agent.md).
Uma linha que a releitura por outra família ou o leitor caro leu de novo, sem
conserto, traz essas leituras em `doubt.others`. Cada uma diz em `same` se o
outro leitor viu o mesmo valor inválido, o que aponta o erro impresso no
documento. A linha lida de dois modos, com o recorte, é o que uma pessoa
confere, e a resposta dela é um rótulo para treinar o leitor.
`doc.crop(page, bbox)` devolve o PNG do recorte, para mostrar a quem decide.
`doc.render(page)` devolve a página inteira, na mesma resolução: as caixas
normalizadas dos chunks caem nela sem conversão. `docaudit.doc_id_for(caminho)`
dá o `doc_id` de um arquivo sem abri-lo, para saber se ele já foi lido.

## Lote de muitos autos

Threads ajudam pouco num lote: o acesso ao PDF passa por um lock, e o PP-OCR
roda uma chamada por vez dentro de um processo. O paralelismo que rende é um
processo por documento. O ONNX Runtime usa todos os núcleos em cada chamada,
e com vários processos eles disputam os mesmos núcleos: `threads=` divide os
núcleos entre os processos. O Tesseract lê `OMP_THREAD_LIMIT`. Os processos
partilham um arquivo de cache: quem grava espera o outro terminar.

Leitores, cache e documento aberto não passam de um processo a outro, e o
macOS e o Linux a partir do Python 3.14 iniciam cada processo do zero. Por
isso cada processo monta os seus. Na primeira execução os pesos são baixados,
e o primeiro auto vai sozinho, antes do pool, para que um processo só faça o
download.

```python
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import docaudit
from docaudit import Budget, ModelCallCache
from docaudit.backends.ppocr import PPOCR

CACHE = Path("cache/docaudit.sqlite")
OUT = Path("saida")
PROCESSES = 4
THREADS = max(1, (os.cpu_count() or 1) // PROCESSES)


def read_one(pdf: Path) -> str:
    # Uma conexão por processo, no mesmo arquivo; a segunda execução do lote
    # lê do cache.
    cache = ModelCallCache(CACHE)
    try:
        result = docaudit.process(
            pdf,
            policy="evidence",
            cheap=["text_layer", PPOCR(threads=THREADS)],
            budget=Budget(max_strong_fraction=0.05),
            cache=cache,
        )
    finally:
        cache.close()
    (OUT / f"{pdf.stem}.json").write_text(result.model_dump_json())
    return pdf.name


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    autos = sorted(Path("autos").glob("*.pdf"))
    # O primeiro auto vai sozinho: os pesos são baixados uma vez, antes do pool.
    print("pronto:", read_one(autos[0]))
    with ProcessPoolExecutor(max_workers=PROCESSES) as pool:
        for name in pool.map(read_one, autos[1:]):
            print("pronto:", name)
```

Com uma GPU, o mesmo lote usa `PPOCR(engine="cuda")` em poucos processos
que partilham a placa: a CPU de cada um renderiza e recorta enquanto a placa
reconhece. `threads=` continua dividindo a CPU entre eles. A detecção roda na
resolução da página, e a digitalização grande pede memória da placa: numa de
8 GB, dois processos leem tudo; com três, algumas páginas falham por falta de
memória. A página que falha não some calada: a cascata a registra em
`failures` da decisão da página, com a mensagem do ONNX Runtime, e `incomplete`
diz que nenhum outro leitor leu no lugar.

Sem GPU, o extra `openvino` faz o PP-OCR ler o mesmo lote na CPU mais
depressa, com o mesmo texto; ver [Configuração](configuration.md#ppocr).

## Guardar a leitura para treinar depois

O que se guarda é o PDF e o `Result` em JSON, não imagens. O `doc_id` é o
hash dos bytes do PDF: ele liga os dois, e diz se um arquivo já foi lido.
Qualquer recorte sai de novo de `Document.crop(page, bbox)`, na resolução
em que os leitores viram a página, com a folga que o treino pedir.
`result.run` diz com que leitores, versões e argumentos a leitura saiu.

```python
from pathlib import Path

import docaudit

LEITURAS = Path("leituras")


def keep(pdf: Path, **kwargs) -> docaudit.Result:
    result = docaudit.process(pdf, **kwargs)
    LEITURAS.mkdir(exist_ok=True)
    (LEITURAS / f"{result.doc_id}.json").write_text(result.model_dump_json())
    return result
```

Uma linha que a releitura por outra família consertou, ou que o leitor
caro substituiu por outro texto, fica em `result.others` com `replaced`: a leitura que
saiu ao lado da que ficou. O par é um exemplo de treino para o leitor que
errou, no formato de rótulo do PaddleOCR, uma imagem e o texto separados
por tabulação:

```python
from docaudit import Document, Result


def pairs(pdf: Path, out: Path) -> list[str]:
    stored = LEITURAS / f"{docaudit.doc_id_for(pdf)}.json"
    result = Result.model_validate_json(stored.read_text())
    lines = {c.id: c for c in result.chunks}
    rows: list[str] = []
    out.mkdir(exist_ok=True)
    with Document(pdf, dpi=result.run.dpi) as doc:
        for other in result.others:
            kept = lines[other.line]
            # Uma linha só dos dois lados: o leitor caro que leu a página
            # inteira num trecho não dá rótulo de linha.
            if not other.replaced or "\n" in kept.text:
                continue
            old = other.reading
            name = f"{result.doc_id}_{old.id}.png"
            (out / name).write_bytes(doc.crop(old.page, old.bbox))
            rows.append(f"{name}\t{kept.text}")
    return rows
```

O rótulo é a leitura de outro leitor, não a de uma pessoa. A releitura
que conferiu passou nas verificações; a linha do leitor caro entra no
lugar mesmo sem valor a conferir. Uma decisão humana sobre a linha, quando
houver, fica no lugar dele. `result.run.versions[old.source]` diz que pesos erraram:
guarde-a com o par, e uma rodada de treino sabe de que modelo são os erros
que corrige. Separe treino e teste por documento, ou pelo processo a que
ele pertence, antes de recortar: as páginas de um mesmo auto repetem o
cabeçalho, a tarja e os nomes, e um teste com páginas do treino mede
memória.

## Notas fiscais e boletos: encaminhar pelos códigos

A chave de acesso de uma nota fiscal, a linha digitável de um boleto e o
código de arrecadação de uma guia já saem em `Result.entities` por padrão,
com o estado que os dígitos verificadores deram. Eles não encaminham a
página por omissão. Num lote de notas e boletos, em que uma chave lida
errada é o que mais importa, ponha-os na política:

```python
import docaudit
from docaudit import Budget
from docaudit.backends.ppocr import PPOCR
from docaudit.policies import (
    ARRECADACAO,
    BOLETO,
    DEFAULT_SIGNALS,
    NFE_KEY,
    EvidenceRouter,
    FailsCheck,
)

result = docaudit.process(
    "notas.pdf",
    policy=EvidenceRouter([*DEFAULT_SIGNALS, *map(FailsCheck, (NFE_KEY, BOLETO, ARRECADACAO))]),
    budget=Budget(max_strong_pages=20),
    strong=PPOCR("v6-medium"),
)
```

Um campo que a biblioteca não traz entra do mesmo jeito, como um `Check`
seu: ver [Entidades](entities.md#um-campo-do-seu-tipo-de-documento).

## A tarja e a folha de outro sistema

Por omissão, `Page.stamp` procura a tarja do e-SAJ, e `Page.folha` o
carimbo `fls. N`. Os outros sistemas imprimem outra coisa, e cada um entra
pelo nome do formato ou por um formato próprio:

```python
import re

import docaudit
from docaudit.policies import Check, StampFormat

result = docaudit.process(
    "autos.pdf",
    stamps=["e-saj", "pje", "projudi-pr", "projudi-go", "eproc"],
    folhas=["folha", "pagina-projudi"],
)

MEU = StampFormat(
    "meu-sistema",
    re.compile(
        r"Assinado em (?P<date>\d{2}/\d{2}/\d{4}) (?P<time>\d{2}:\d{2}:\d{2}) .* Doc\. (?P<code>\d+)"
    ),
    time_format="%H:%M:%S",
    process_check=None,  # a tarja não traz número CNJ
)
PAGINA = Check("pagina", re.compile(r"Folha (?P<number>\d+)"), lambda _: True)
result = docaudit.process("autos.pdf", stamps=[MEU], folhas=[PAGINA])
```

| nome | sistema | o que vira `code` |
|---|---|---|
| `e-saj` | e-SAJ, de São Paulo e de outros tribunais | o código de conferência |
| `pje` | PJe | o número do documento |
| `projudi-pr` | Projudi do TJPR | o identificador da validação |
| `projudi-go` | Projudi do TJGO | o código de localização |
| `eproc` | eproc | o evento e o anexo |

Fora o `e-saj`, os formatos são pontos de partida, medidos em poucas
páginas de cada sistema: confira-os nos seus autos antes de confiar.
`pagina-projudi` lê a página do processo no pé do Projudi. No eproc, a
`Página` do rodapé é a do anexo, e ela não é folha.
