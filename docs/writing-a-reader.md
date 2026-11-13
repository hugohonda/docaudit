# Escrever um leitor

Este guia escreve um leitor próprio, para pôr outro motor de reconhecimento óptico de caracteres (OCR) ou outro
modelo na cascata barata ou no lugar do leitor caro. Um leitor implementa
`Reader`, um `Protocol`: não há classe-base para herdar, e o pyright confere a
forma do leitor. O mesmo contrato serve às duas etapas. A diferença entre o
leitor barato e o leitor caro é quem decide chamá-lo, não a forma dele.

A assinatura de `Reader`, de `PageView` e de `RegionView` está em
[Leitores](reference/readers.md).

## O mínimo

Um leitor tem três atributos e um método. O exemplo lê a página com o
Tesseract, palavra por palavra, pelo `pytesseract`:

```python
from collections.abc import Sequence

from docaudit import BBox, Chunk, PageView, process


class WordOCR:
    name = "word-ocr"
    external = False  # True se envia a página para fora da máquina
    output_version = "1:lang=por:psm=3"  # tudo o que muda a leitura

    def read(self, view: PageView) -> Sequence[Chunk]:
        import pytesseract  # import pesado fica dentro do método

        image = view.pixels(grayscale=True)
        width, height = image.size
        data = pytesseract.image_to_data(image, lang="por", output_type=pytesseract.Output.DICT)
        out: list[Chunk] = []
        for text, conf, x, y, w, h in zip(
            data["text"], data["conf"], data["left"], data["top"], data["width"], data["height"]
        ):
            if not text.strip():
                continue
            bbox = BBox.from_pixels(x, y, x + w, y + h, width_px=width, height_px=height)
            out.append(
                Chunk.make(
                    view.page,
                    bbox,
                    self.name,
                    text,
                    confidence=float(conf) / 100,
                    reading_order=len(out),
                )
            )
        return out


# A instância entra na cascata ou em strong=, como qualquer leitor.
result = process("documento.pdf", cheap=["text_layer", WordOCR()])
```

O que cada atributo faz:

- `name` é o nome que fica em `Chunk.source` de cada linha.
- `external = True` declara que o leitor manda a página para fora da máquina.
  `process()` o recusa sem `allow_external=True`.
- `output_version` entra na chave do cache. Pesos, idioma, prompt, opções do
  motor e o jeito de partir a página em trechos: tudo o que muda a leitura
  sem mudar o nome tem de estar nela. Sem isso, o cache devolve a leitura
  antiga.

A caixa é normalizada a [0, 1], com origem no canto superior esquerdo.
`BBox.from_pixels` converte a caixa em pixels que o motor devolveu.

O leitor que gira a página para ler informa o giro em `Chunk.make(turn=)` e
devolve a caixa no sistema da imagem, com `BBox.unturned`. Sem isso, a
detecção de elementos fixos julga a linha como se a página estivesse em pé.

## Registrar o nome

Declare o entry point, e o leitor passa a ser aceito pelo nome em qualquer
projeto que instale o seu pacote, como `cheap=["text_layer", "word-ocr"]`:

```toml
[project.entry-points."docaudit.backends"]
word-ocr = "my_package.ocr:WordOCR"
```

`docaudit.get_backend("word-ocr")` devolve a classe registrada.
`docaudit.backends.ppocr.PPOCR` é um leitor completo e serve de modelo.
`docaudit.backends.vlm.VLM` é o modelo para um leitor de visão e linguagem:
recebe o preset de prompts no construtor, declara-o em `output_version` e
pede a imagem em cor.

## O que `PageView` entrega

| membro | custo | quando usar |
|---|---|---|
| `view.page` | nenhum | metadados, dimensões e substrato |
| `view.text_lines()` | baixo | a camada de texto, uma linha por item, com caixa |
| `view.pixels(grayscale=True)` | alto | a página renderizada, como imagem do Pillow |
| `view.image(grayscale=True)` | alto | a mesma renderização em PNG, para um motor que pede o arquivo |
| `view.region(box)` | o do recorte | uma `RegionView` com só a parte `box` da página |
| `view.rendered` | nenhum | `True` depois que alguém pediu os pixels |

Peça só o que usar: o que não for pedido não é calculado. Cada modo de cor é
renderizado no máximo uma vez por página. Um motor treinado em cor, como o
PP-OCR e os modelos de visão e linguagem, pede `grayscale=False`.

## Quando o leitor recebe uma região

`rendered` decide o que vem depois. Um leitor que devolve texto sem pedir os pixels é tratado como camada de texto.
A leitura dele não cobre os rasters de `Page.unread`, as imagens da página
que nenhuma camada leu. O leitor seguinte
da cascata lê esses rasters.

Os rasters ganham a folga `RASTER_MARGIN` em cada lado, e os que se tocam
viram um grupo. O leitor seguinte recebe uma `RegionView` por grupo. Um
grupo que cobre a página inteira é lido como a página.

A `RegionView` cumpre o mesmo contrato, com três diferenças:

- `view.pixels()` e `view.image()` devolvem só o recorte.
- `view.text_lines()` volta vazio, porque a região é o que nenhuma camada leu.
- `view.page` descreve o recorte: as dimensões em pixel são as dele, e as
  caixas que o leitor devolve são relativas a ele.

`view.box` é o recorte na página, e `view.rasters` são os rasters que ele
contém, em coordenadas da página. Escreva o leitor como para a página
inteira. `process()` leva as caixas de volta à página, refaz os ids e
descarta a linha cujo centro cai em algo já lido.

## Quando a leitura falha

O tipo da exceção diz a `process()` o tamanho da falha:

| exceção | significa | o que `process()` faz |
|---|---|---|
| `RuntimeError` | esta página não pôde ser lida | na cascata barata, passa ao leitor seguinte; no leitor caro, a página fica com a leitura barata, quando a política a fez. A página entra em `pages_cheap_failed` ou `pages_strong_failed`, e sai um `RuntimeWarning` |
| `ConnectionError` | o serviço não está lá | interrompe o documento, porque as páginas seguintes falhariam do mesmo jeito |
| qualquer outra | um defeito do leitor | interrompe o documento |

Traduza para `RuntimeError` só o que é desta página: um tempo esgotado, uma
resposta que não se lê, um erro do motor numa imagem. Um binário que falta,
ou um módulo quebrado, não é desta página. Relance-o como `ImportError`,
mesmo que o motor o embrulhe num tipo próprio.

## Quando o leitor não é para a página

Um leitor que devolve uma sequência vazia passa a página ao seguinte da
cascata, sem falha nem aviso. Assim um leitor fica só com as páginas que são
dele: olha `view.page.substrate` ou `view.page.unread` e devolve `[]` nas
outras.

```python
from collections.abc import Sequence

from docaudit import Chunk, PageView, Reader, Substrate


class ScansOnly:
    """Passa ao leitor de dentro só as páginas que são imagem pura."""

    def __init__(self, inner: Reader) -> None:
        self.inner = inner
        self.name, self.external = inner.name, inner.external
        self.output_version = f"{inner.output_version}:scans-only"

    def read(self, view: PageView) -> Sequence[Chunk]:
        if view.page.substrate is not Substrate.IMAGE_ONLY:
            return []
        return self.inner.read(view)
```

Para não ler a imagem pequena de uma página nato-digital, como o logotipo e o
brasão do cabeçalho, use primeiro `process(min_raster_fraction=)`. O raster
menor que essa fração da página não chega a nenhum leitor de pixels, e fica
em `Page.unread` e em `Result.figures()`, sem linha.

!!! warning "Parâmetro não calibrado"
    O padrão de `min_raster_fraction`, `0.0`, lê todos os rasters. O valor
    que separa um logotipo de uma figura com texto depende do acervo e não
    foi medido. Meça-o nos seus documentos.

Um invólucro como o abaixo fica para a regra que é do próprio leitor, como
pular só os rasters que um motor caro não deve ver:

```python
from collections.abc import Sequence

from docaudit import Chunk, PageView, Reader
from docaudit.pdf import RegionView


class SkipSmallRasters:
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
herda. Ela confere o que o `Protocol` não garante: caixas dentro da página,
ids determinísticos, página em branco sem texto inventado, confiança em
[0, 1].

`tests/support` não vai no pacote distribuído. Para conferir um leitor seu,
copie `contracts.py` e `fixtures.py` do repositório para a sua suíte, herde
`ReaderContract` e forneça a fixture `reader`.
