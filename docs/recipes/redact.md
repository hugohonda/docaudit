# Redigir dados pessoais

Cada entidade sai com a caixa das linhas em que está. Um `Check` com dígito
verificador acha o valor mesmo quando o reconhecimento óptico de caracteres (OCR) trocou a pontuação. A redação precisa disso: a lista do que cobrir, com a posição na página e o
trecho no texto. Os identificadores opcionais (`IDENTIFIERS`) entram na lista quando o
tipo de documento os traz.

```python
import io

from PIL import Image, ImageDraw

from docaudit import Document, Entity
from docaudit.policies import DEFAULT_ENTITIES, IDENTIFIERS

PERSONAL = {"CPF", "CNPJ", "PIS", "título de eleitor", "CNH", "RENAVAM"}


def mask(texts: dict[str, str], entity: Entity) -> None:
    """Troca por `#` cada caractere do valor nas linhas dele, sem mudar o comprimento."""
    assert entity.span is not None
    begin, end = entity.span
    offset = 0
    for cid in entity.chunk_ids:
        line = texts[cid]
        lo, hi = max(begin - offset, 0), min(end - offset, len(line))
        if lo < hi:
            texts[cid] = line[:lo] + "#" * (hi - lo) + line[hi:]
        offset += len(line) + 1


with Document("relatorio.pdf") as doc:
    result = doc.read(entities=[*DEFAULT_ENTITIES, *IDENTIFIERS], spans=True)
    found = [e for e in result.entities if e.kind in PERSONAL]
    for index in {e.page for e in found}:
        image = Image.open(io.BytesIO(doc.render(index, grayscale=False)))
        draw = ImageDraw.Draw(image)
        for entity in found:
            if entity.page == index:
                draw.rectangle(entity.bbox.to_pixels(image.width, image.height), fill="black")
        image.save(f"relatorio-p{index}-redigido.png")

texts = {c.id: c.text for c in result.chunks}
for entity in found:
    mask(texts, entity)
text = "\n\n".join(
    "\n".join(texts[c.id] for c in chunks) for chunks in result.by_page().values()
)
```

A caixa da entidade cobre as linhas inteiras em que o valor está, e não só os
dígitos: é a caixa que o leitor devolveu.

O texto é redigido pela posição, e não pela busca do valor. `Entity.value`
sai com os hífens e espaços tipográficos trocados pelo ASCII e com os espaços
colapsados. O texto das linhas fica como foi lido. Um CPF com o hífen
U+2010 ou com espaço não separável, e um valor partido entre duas linhas,
não seriam achados por `text.replace(entity.value, ...)`. `spans=True` põe em
`Entity.span` o começo e o fim do valor no texto das linhas de
`entity.chunk_ids`, unidas por quebra de linha. A máscara tem o comprimento
do valor, e por isso a posição de outro valor na mesma linha continua certa.

O texto redigido é montado de `texts`. O `result` continua com os valores
em `entities`, em `others` e em `to_markdown()`: não o entregue.

O que a redação não cobre:

- o valor que nenhum leitor leu;
- o que não tem forma fixa, como nome e endereço: a biblioteca não os
  procura ([Entidades padrão](../entities.md#o-que-fica-de-fora));
- o valor que a forma do campo não casou: ele não vira entidade
  ([Comportamentos conhecidos](../limits.md#comportamentos-conhecidos)).

Confira a imagem redigida antes de publicá-la. O que fica no disco durante a
leitura está em [Segurança dos dados](../security.md).
