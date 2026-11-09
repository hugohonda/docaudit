# Redigir dados pessoais

Cada entidade sai com a caixa das linhas em que está. Um `Check` com dígito
verificador acha o valor mesmo quando o reconhecimento óptico de caracteres (OCR) trocou a pontuação. A redação precisa disso: a lista do que cobrir, com a posição na página e o
trecho no texto. Os identificadores opcionais (`IDENTIFIERS`) entram na lista quando o
tipo de documento os traz.

```python
import io

from PIL import Image, ImageDraw

from docaudit import Document
from docaudit.policies import DEFAULT_ENTITIES, IDENTIFIERS

PERSONAL = {"CPF", "CNPJ", "PIS", "título de eleitor", "CNH", "RENAVAM"}

with Document("relatorio.pdf") as doc:
    result = doc.read(entities=[*DEFAULT_ENTITIES, *IDENTIFIERS])
    found = [e for e in result.entities if e.kind in PERSONAL]
    for index in {e.page for e in found}:
        image = Image.open(io.BytesIO(doc.render(index, grayscale=False)))
        draw = ImageDraw.Draw(image)
        for entity in found:
            if entity.page == index:
                draw.rectangle(entity.bbox.to_pixels(image.width, image.height), fill="black")
        image.save(f"relatorio-p{index}-redigido.png")

text = result.to_markdown()
for entity in found:
    text = text.replace(entity.value, "[redigido]")
```

A caixa da entidade cobre as linhas inteiras em que o valor está, e não só os
dígitos: é a caixa que o leitor devolveu.

O que a redação não cobre:

- o valor que nenhum leitor leu;
- o que não tem forma fixa, como nome e endereço: a biblioteca não os
  procura ([Limites](../limits.md));
- o valor numa saída que não é `to_markdown`. Nesse caso, `entity.chunk_ids`
  diz que linhas tocar.

Confira a imagem redigida antes de publicá-la. O que fica no disco durante a
leitura está em [Segurança dos dados](../security.md).
