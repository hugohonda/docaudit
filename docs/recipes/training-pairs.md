# Guardar a leitura para treinar

Guarde o PDF e o `Result` em JSON, não as imagens. O `doc_id` é o hash dos
bytes do PDF: ele liga os dois arquivos e diz se um PDF já foi lido. Qualquer
recorte sai de novo de `Document.crop(page, bbox)`, na resolução em que os
leitores viram a página. `result.run` diz com que leitores, versões e
argumentos a leitura saiu.

```python
from pathlib import Path
from typing import Any

from docaudit import Result, process

READS = Path("leituras")


def keep(pdf: Path, **kwargs: Any) -> Result:
    result = process(pdf, **kwargs)
    READS.mkdir(exist_ok=True)
    (READS / f"{result.doc_id}.json").write_text(result.model_dump_json())
    return result
```

## Tirar pares de treino

A releitura por outra família pode consertar uma linha, e o leitor caro pode
trocá-la por outro texto. Nos dois casos, a linha que saiu fica em
`result.others`, com `replaced`. Numa digitalização com camada de OCR, a
camada de texto também entra no lugar das linhas dos pixels: na tarja e na
folha à vista, e no identificador que confere na camada oculta. A linha
que ficou tem então `source` igual a `text_layer`, e pode cobrir só parte
da linha que saiu. O código abaixo pula esses casos. É a leitura que saiu ao lado da que ficou. O par é um exemplo de
treino para o leitor que errou. O formato abaixo é o rótulo do PaddleOCR: o
nome da imagem e o texto, separados por tabulação.

```python
from pathlib import Path

from docaudit import Document, Result, doc_id_for

READS = Path("leituras")


def pairs(pdf: Path, out: Path) -> list[str]:
    stored = READS / f"{doc_id_for(pdf)}.json"
    result = Result.model_validate_json(stored.read_text())
    lines = {c.id: c for c in result.chunks}
    rows: list[str] = []
    out.mkdir(exist_ok=True)
    with Document(pdf, dpi=result.run.dpi) as doc:
        for other in result.others:
            kept = lines[other.line]
            # Uma linha só dos dois lados: o leitor caro que leu a página
            # inteira num trecho não dá rótulo de linha. A linha da camada
            # de texto pode cobrir só parte da linha que saiu.
            if not other.replaced or "\n" in kept.text or kept.source == "text_layer":
                continue
            old = other.reading
            name = f"{result.doc_id}_{old.id}.png"
            (out / name).write_bytes(doc.crop(old.page, old.bbox))
            rows.append(f"{name}\t{kept.text}")
    return rows
```

O rótulo é a leitura de outro leitor, não a de uma pessoa:

- a releitura por outra família só troca a linha quando o valor novo passa
  na verificação;
- a linha do leitor caro entra no lugar mesmo sem valor a conferir;
- uma decisão humana sobre a linha, quando houver, substitui esse rótulo.

`result.run.versions[old.source]` diz que pesos erraram. Guarde essa versão
com o par, e cada rodada de treino sabe de que modelo são os erros que
corrige.

Separe treino e teste por documento, ou pelo processo judicial a que ele
pertence, antes de recortar. As páginas de um mesmo processo repetem o
cabeçalho, a tarja e os nomes, e um teste com páginas do treino mede
memória, não leitura.

Os campos de `Run` e de `OtherReading` estão em
[Campos do resultado](../response/fields.md).
