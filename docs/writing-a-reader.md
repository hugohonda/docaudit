# Escrevendo um leitor

Um leitor implementa `Reader`. É um `Protocol`: não há classe-base para herdar,
e a conformidade é verificada estruturalmente pelo pyright. O mesmo contrato
serve à cascata barata e ao tier caro: a diferença entre os tiers é quem decide
chamar o leitor, não a forma dele.

```python
from collections.abc import Sequence

from docaudit.pdf import PageView
from docaudit.types import BBox, Chunk, Page


class MyOCR:
    name = "my-ocr"
    external = False  # True se envia dados para fora da máquina
    output_version = "1:weights=v3:lang=por"  # tudo o que muda a leitura

    def read(self, view: PageView) -> Sequence[Chunk]:
        image = view.image()
        page = view.page
        px = page.dimensions

        out: list[Chunk] = []
        for x0, y0, x1, y1, text, conf in run_my_engine(image):
            bbox = BBox.from_pixels(x0, y0, x1, y1, width_px=px.width_px, height_px=px.height_px)
            out.append(
                Chunk.make(
                    page,
                    bbox,
                    self.name,
                    text,
                    confidence=conf,
                    reading_order=len(out),
                )
            )
        return out
```

`output_version` entra na chave do cache. Pesos, idioma, prompt, flags do motor
e o formato em que o leitor parte a página em chunks: tudo o que muda a leitura
sem mudar o nome tem de estar nela, senão o cache serve a leitura antiga.

O leitor que gira a página para ler diz o giro em `turn=` e devolve a caixa no
sistema da imagem, com `BBox.unturned`. Sem isso, os elementos fixos julgam a
linha como se a página estivesse em pé.

Declare o entry point e o leitor passa a ser resolvível pelo nome em qualquer
projeto que instale o seu pacote:

```toml
[project.entry-points."docaudit.backends"]
my-ocr = "my_package.ocr:MyOCR"
```

`docaudit.backends.ppocr.PPOCR` é um leitor completo e serve de exemplo.
`docaudit.backends.vlm.VLM` é o exemplo de um modelo de visão e linguagem:
recebe o preset de prompts no construtor, o declara em `output_version`, e
pede `view.image(grayscale=False)`.

## O que `PageView` entrega

| método | custo | quando usar |
|---|---|---|
| `view.page` | nulo | metadados e substrato |
| `view.text_lines()` | baixo | texto embutido, uma linha por item, com caixa |
| `view.image(grayscale=True)` | alto | qualquer coisa que leia pixels |

Peça só o que usar: o que não for pedido não é calculado.

## Quando o leitor recebe uma região

Um leitor que devolve texto sem chamar `view.image()` é tratado como uma
camada de texto: a leitura dele não cobre os rasters de `Page.unread`. O
leitor seguinte da cascata recebe então uma `RegionView`,
com a menor caixa que contém essas regiões.

A `RegionView` cumpre o mesmo contrato, com três diferenças, e diz o que
cobre: `view.box` é o recorte na página, e `view.rasters` as imagens da
página que ele lê. `view.image()`
devolve só o recorte. `view.text_lines()` volta vazio, porque a região é o que
nenhuma camada leu. E `view.page` descreve o recorte: as dimensões em pixel são
as dele, e as caixas que o leitor devolve são relativas a ele. Escreva o
leitor como para a página inteira. `process()` leva as caixas de volta à
página, refaz os ids e descarta a linha cujo centro cai em algo já lido.

## Quando a leitura falha

O tipo da exceção diz a `process()` o tamanho da falha.

- `RuntimeError`: esta página não pôde ser lida. Na cascata barata, o leitor
  seguinte tenta; no leitor caro, a página fica com a leitura barata. A
  página entra em `pages_cheap_failed` ou `pages_strong_failed`, e sai um
  `RuntimeWarning`.
- `ConnectionError`: o serviço não está lá. O documento para, porque as
  páginas seguintes falhariam do mesmo jeito.
- Qualquer outra exceção é um defeito do leitor, e também para o documento.

Traduza para `RuntimeError` só o que é desta página: um tempo esgotado, uma
resposta que não se lê, um erro do motor numa imagem. Um binário que falta
não é desta página, nem um módulo quebrado: relance-o como `ImportError`,
mesmo que o motor o embrulhe num tipo próprio.

## Quando o leitor não é para a página

Um leitor que devolve uma sequência vazia passa a página ao seguinte da
cascata, sem falha nem aviso. É assim que um leitor fica só com as páginas
que são dele: olha `view.page.substrate`, ou `view.page.unread`, e devolve
`[]` nas outras.

```python
from docaudit.types import Substrate


class ScansOnly:
    name = "scans-only"
    external = False
    output_version = "1"

    def read(self, view: PageView) -> Sequence[Chunk]:
        if view.page.substrate is not Substrate.IMAGE_ONLY:
            return []
        return read_pixels(view)
```

Um leitor que não quer ler a imagem pequena, como o logotipo de uma página
nato-digital, devolve `[]` na região dela, e a página fica com a camada de
texto, numa chamada só de `process()`. O limiar é seu, medido nos seus
autos: a biblioteca não o fixa.

```python
from docaudit.pdf import RegionView


class SkipLogos:
    def __init__(self, inner: Reader, min_area: float) -> None:
        self.inner, self.min_area = inner, min_area
        self.name, self.external = inner.name, inner.external
        self.output_version = f"{inner.output_version}:min_area={min_area}"

    def read(self, view: PageView) -> Sequence[Chunk]:
        if isinstance(view, RegionView) and view.rasters:
            if max(r.area for r in view.rasters) < self.min_area:
                return []
        return self.inner.read(view)
```

## A suíte de contrato

`tests/support/contracts.py` traz `ReaderContract`, que todo leitor do pacote
herda. Ela verifica o que o Protocol não garante: caixas dentro da página, ids
determinísticos, página em branco sem texto inventado, confiança em `[0, 1]`.

`tests/support` não vai no pacote distribuído. Para verificar um leitor de
fora, copie `contracts.py` e as fixtures de `fixtures.py` para a sua suíte,
herde `ReaderContract` e forneça a fixture `reader`.
