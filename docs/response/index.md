# Formato da resposta

`process()` e `Document.read()` devolvem um `Result`. É um modelo Pydantic
congelado: `result.model_dump_json()` serializa tudo, e
`Result.model_json_schema()` descreve o formato em JSON Schema. Cada campo
está descrito em [Campos do resultado](fields.md).

## Exemplo

O documento é um PDF nato-digital de uma página, com cinco linhas de texto,
uma delas com um CPF. Serve qualquer PDF assim, gerado por um editor de
texto. A camada de texto é a única leitura, e a política é `evidence`.

```python
import docaudit
from docaudit import Budget

result = docaudit.process(
    "mandado.pdf",
    policy="evidence",
    budget=Budget(max_strong_pages=1, max_seconds=60),
    cheap=["text_layer"],
)
print(result.model_dump_json(indent=2))
```

A saída abaixo é a real, resumida. As caixas estão arredondadas a quatro
casas. Os segundos medidos saíram e ficou `"..."` no lugar deles: eles mudam
de uma máquina para outra. Em `spent`, saíram as contagens que vieram
zeradas. Os objetos pequenos estão numa linha só.

```json
{
  "doc_id": "502248ed14c30d64",
  "pages": [
    {
      "doc_id": "502248ed14c30d64",
      "index": 0,
      "dimensions": {"width_pt": 595.0, "height_pt": 842.0, "width_px": 1653, "height_px": 2339, "dpi": 200},
      "substrate": "born_digital",
      "substrate_evidence": {"chars": 177.0, "visible_text": 5.0, "invisible_text": 0.0, "covered_text": 0.0, "unmapped_text": 0.0, "unread_regions": 0.0},
      "stamp": null,
      "folha": null,
      "unread": [],
      "hidden_fonts": []
    }
  ],
  "chunks": [
    {
      "id": "7aaaba4eeb73f7673fb4a2b5",
      "page": 0,
      "bbox": {"x0": 0.1199, "y0": 0.0818, "x1": 0.4807, "y1": 0.0976},
      "text": "MANDADO DE PENHORA",
      "source": "text_layer",
      "confidence": null,
      "reading_order": 0,
      "turn": 0,
      "kind": null,
      "line_break_hyphens": [],
      "region": null,
      "furniture": false
    },
    {
      "id": "aab98c511dbaaff729b1e977",
      "page": 0,
      "bbox": {"x0": 0.1191, "y0": 0.1355, "x1": 0.4312, "y1": 0.145},
      "text": "Processo 9001087-60.2022.8.26.0390",
      "source": "text_layer",
      "confidence": null,
      "reading_order": 1,
      "turn": 0,
      "kind": null,
      "line_break_hyphens": [],
      "region": null,
      "furniture": false
    },
    {
      "id": "43f9d6099cd55f3966fc139b",
      "page": 0,
      "bbox": {"x0": 0.1191, "y0": 0.1591, "x1": 0.5639, "y1": 0.1705},
      "text": "Executado: MARCOS PEREIRA, CPF 529.982.247-25",
      "source": "text_layer",
      "confidence": null,
      "reading_order": 2,
      "turn": 0,
      "kind": null,
      "line_break_hyphens": [],
      "region": null,
      "furniture": false
    },
    {
      "id": "b7f86402be4e5d952dc07464",
      "page": 0,
      "bbox": {"x0": 0.1177, "y0": 0.1822, "x1": 0.4097, "y1": 0.1942},
      "text": "Valor: R$ 12.500,00 em 10/03/2024",
      "source": "text_layer",
      "confidence": null,
      "reading_order": 3,
      "turn": 0,
      "kind": null,
      "line_break_hyphens": [],
      "region": null,
      "furniture": false
    },
    {
      "id": "b11e125711a68f06f5027d34",
      "page": 0,
      "bbox": {"x0": 0.1191, "y0": 0.2066, "x1": 0.4836, "y1": 0.2187},
      "text": "Exequente: ANA LIMA, CPF 111.444.777-30",
      "source": "text_layer",
      "confidence": null,
      "reading_order": 4,
      "turn": 0,
      "kind": null,
      "line_break_hyphens": [],
      "region": null,
      "furniture": false
    }
  ],
  "decisions": [
    {
      "page": 0,
      "tier": "cheap",
      "reason": "sem evidência de falha",
      "signals": {},
      "steps": [
        "tier barato: text_layer leu 5 linha(s)",
        "política: sem evidência de falha"
      ],
      "failures": [],
      "incomplete": false,
      "seconds": {"cheap": "..."}
    }
  ],
  "entities": [
    {
      "kind": "CNJ",
      "value": "9001087-60.2022.8.26.0390",
      "state": "confirmed",
      "page": 0,
      "bbox": {"x0": 0.1191, "y0": 0.1355, "x1": 0.4312, "y1": 0.145},
      "chunk_ids": ["aab98c511dbaaff729b1e977"],
      "span": null,
      "printed": null
    },
    {
      "kind": "CPF",
      "value": "529.982.247-25",
      "state": "confirmed",
      "page": 0,
      "bbox": {"x0": 0.1191, "y0": 0.1591, "x1": 0.5639, "y1": 0.1705},
      "chunk_ids": ["43f9d6099cd55f3966fc139b"],
      "span": null,
      "printed": null
    },
    {
      "kind": "valor em reais",
      "value": "R$ 12.500,00",
      "state": "well_formed",
      "page": 0,
      "bbox": {"x0": 0.1177, "y0": 0.1822, "x1": 0.4097, "y1": 0.1942},
      "chunk_ids": ["b7f86402be4e5d952dc07464"],
      "span": null,
      "printed": null
    },
    {
      "kind": "data",
      "value": "10/03/2024",
      "state": "well_formed",
      "page": 0,
      "bbox": {"x0": 0.1177, "y0": 0.1822, "x1": 0.4097, "y1": 0.1942},
      "chunk_ids": ["b7f86402be4e5d952dc07464"],
      "span": null,
      "printed": null
    },
    {
      "kind": "CPF",
      "value": "111.444.777-30",
      "state": "failed",
      "page": 0,
      "bbox": {"x0": 0.1191, "y0": 0.2066, "x1": 0.4836, "y1": 0.2187},
      "chunk_ids": ["b11e125711a68f06f5027d34"],
      "span": null,
      "printed": "text_layer"
    }
  ],
  "others": [],
  "spent": {
    "pages_total": 1,
    "pages_cheap": 1,
    "seconds_cheap": "...",
    "seconds": "...",
    "calls": null,
    "tokens_in": null,
    "tokens_out": null,
    "usd": null
  },
  "run": {
    "started_at": "2026-11-09T00:49:02.406306Z",
    "policy": "evidence",
    "budget": {"max_strong_pages": 1, "max_strong_fraction": null, "max_seconds": 60.0},
    "cheap": ["text_layer"],
    "confirm": null,
    "strong": null,
    "reread": "page",
    "trust_layer": "visible",
    "dpi": null,
    "entities": [
      "CPF",
      "CNPJ",
      "CNJ",
      "valor em reais",
      "valor em moeda anterior ao real",
      "data",
      "data com dia da semana",
      "data por extenso",
      "folha",
      "chave de acesso",
      "linha digitável de boleto",
      "código de arrecadação"
    ],
    "stamps": ["e-saj"],
    "folhas": ["folha"],
    "spans": false,
    "min_raster_fraction": 0.0,
    "versions": {"text_layer": "3:pypdfium2=<versão>"}
  },
  "document": {
    "producer": null,
    "creator": null,
    "title": null,
    "author": null,
    "subject": null,
    "keywords": null,
    "created_at": null,
    "modified_at": null,
    "pdf_version": "1.4",
    "tagged": false,
    "form": "none",
    "saves": 1,
    "identifier_changed": null,
    "restricted": false,
    "page_labels": false,
    "signatures": []
  },
  "library_version": "<versão>"
}
```

O segundo CPF tem o dígito verificador errado, e a entidade sai `failed`. Como
o valor veio da camada de texto de uma página nato-digital, nenhum leitor errou
ali: `printed` vale `text_layer`, e o erro é do documento. Pela mesma razão, a
política não encaminhou a página. `calls`, `tokens_in`, `tokens_out` e `usd`
saem `null` porque nenhum leitor desta execução conta tokens.

### Uma página encaminhada

A segunda execução lê um documento digitalizado: uma página parecida com a
primeira, com uma linha de custas a mais e um CPF que confere, rasterizada
em baixa resolução. Serve qualquer digitalização de uma página com um CPF.
O Tesseract lê na etapa barata e o PP-OCR é o leitor caro.

```python
import docaudit

result = docaudit.process(
    "mandado-digitalizado.pdf",
    policy="evidence",
    cheap=["text_layer", "tesseract"],
    strong="ppocr",
)
```

O Tesseract leu `111.444.777-25` no lugar de `111.444.777-35`, e o dígito
verificador falhou. A decisão da página ficou assim, resumida: os segundos
medidos e a confiança do motor deram lugar a `"..."`, e os objetos pequenos
estão numa linha só. O texto exato depende da versão do Tesseract e da fonte
usada para rasterizar, e pode sair diferente em outra máquina.

```json
{
  "page": 0,
  "tier": "strong",
  "reason": "1 x CPF que falha a verificação",
  "signals": {"CPF que falha a verificação": 1, "CNJ que falha a verificação": 1},
  "steps": [
    "tier barato: tesseract leu 6 linha(s)",
    "política: 1 x CPF que falha a verificação",
    "ppocr-v5-latin leu a página inteira: 6 linha(s); substituiu 5 da leitura barata, ficaram 1",
    "1 linha(s) do leitor caro recusada(s): perdeu valor em reais que falha a verificação que a leitura barata trazia; perdeu um valor com vírgula decimal que a leitura barata trazia"
  ],
  "failures": [],
  "incomplete": false,
  "seconds": {"cheap": "...", "confirm": "...", "strong": "..."}
}
```

`reason` cita o primeiro sinal da lista que disparou, e `signals` traz todos. O
PP-OCR leu a página inteira e substituiu cinco linhas do Tesseract. Uma linha
dele foi recusada, porque perdia um valor que a leitura barata trazia. Ela fica
em `others` ao lado da linha do Tesseract, com `check` e o valor que não
trouxe. A linha do Tesseract que saiu fica em `others`, ao lado da que entrou
no lugar dela, com `replaced`:

```json
{
  "line": "e21f8054f1912967086b2b70",
  "reading": {
    "id": "49e8e2cebf8d2b774147ec9f",
    "page": 0,
    "bbox": {"x0": 0.0967, "y0": 0.1819, "x1": 0.3787, "y1": 0.1893},
    "text": "Exequente: ANA LIMA, CPF 111.444.777-25",
    "source": "tesseract",
    "confidence": "...",
    "reading_order": 4,
    "turn": 0,
    "kind": null,
    "line_break_hyphens": [],
    "region": null,
    "furniture": false
  },
  "same": false,
  "replaced": true,
  "check": null,
  "value": null
}
```

A linha que entrou é `Enequente: ANA LIMa, CPE 111.444.777-35`. O PP-OCR errou
letras, mas o CPF dela confere, e a entidade sai `confirmed`. A conferência
olha os valores com regra, e não o resto da linha.

## `Result`

| campo | tipo | o que traz |
|---|---|---|
| `doc_id` | `str` | os primeiros `DOC_ID_HEX_CHARS` dígitos hexadecimais do SHA-256 dos bytes do documento |
| `pages` | `tuple[Page, ...]` | as páginas processadas, na ordem do documento |
| `chunks` | `tuple[Chunk, ...]` | os trechos lidos, página a página |
| `decisions` | `tuple[RoutingDecision, ...]` | uma decisão da política por página |
| `entities` | `tuple[Entity, ...]` | cada valor achado por uma verificação, com estado e linha de origem |
| `others` | `tuple[OtherReading, ...]` | as outras leituras do mesmo lugar de uma linha |
| `spent` | `Spent` | o que a execução gastou |
| `run` | `Run` ou `null` | os leitores, as versões e os argumentos da execução |
| `document` | `DocumentFacts` ou `null` | o que o arquivo PDF diz de si |
| `library_version` | `str` | a versão do pacote que gerou o resultado |

`process()` sempre preenche `run` e `document`. Eles saem `null` só num
resultado lido de um JSON que não traz esses campos.

Nove métodos dão as outras formas de uso:

| método | devolve | para quê |
|---|---|---|
| `by_page()` | `dict[int, list[Chunk]]` | as linhas de cada página na ordem de leitura. A linha sem `reading_order` vai ao fim, de cima para baixo |
| `read_by()` | `dict[int, tuple[str, ...]]` | os leitores que deram linhas a cada página. Mostra o que `substrate` não diz: a folha digitalizada sob uma tarja de texto é `born_digital`, e o corpo vem dos pixels |
| `verification()` | `dict[int, dict[str, dict[str, int]]]` | por página e por verificação, quantos valores em cada estado. A chave `printed` conta as falhas que são do documento |
| `refs()` | `dict[str, Chunk]` | uma referência curta por linha, `p<página>:<posição>`, para citar a linha |
| `cited(refs, value, *, entity=None)` | `list[Chunk]` | as linhas citadas, se `value` está no texto delas; vazio se a citação não confere. Não usa modelo |
| `figures()` | `list[Figure]` | as imagens das páginas nato-digitais, cada uma com as linhas lidas dentro dela |
| `records(*, furniture=True, gap=1.0)` | `list[Record]` | as linhas de cada página em fileiras e blocos, só pela posição das caixas |
| `pieces()` | `list[Piece]` | as páginas seguidas com a mesma tarja |
| `to_markdown(*, furniture=True, annotated=False)` | `str` | o texto, uma linha por trecho, com um comentário HTML por página |

!!! warning "`gap` não está calibrado"
    Em `records()`, fileiras seguidas cujo vão não passa de `gap` vezes a
    altura mediana das linhas da página ficam no mesmo bloco. `gap` é a razão
    entre o vão que separa dois parágrafos e a altura de uma linha, e muda com
    o entrelinhamento do documento. Nenhuma medição fixou o padrão `1.0`.

## O mesmo documento em três formas

As três formas servem a consumidores diferentes, e todas levam ao mesmo
`Chunk`:

| forma | para quem | como se chega à origem |
|---|---|---|
| `result.model_dump_json()` | um programa, um banco de dados, uma ferramenta de revisão | `Chunk.id`, estável entre execuções; página e caixa no próprio trecho |
| `result.to_markdown()` | busca, leitura humana, um índice | o comentário de cada página |
| `result.to_markdown(annotated=True)` | um modelo de linguagem | a referência `p<página>:<posição>`, por `result.refs()` |

`to_markdown()` dá o texto do exemplo assim. O comentário diz o índice da
página e quem a leu:

```text
<!-- página 0 · text_layer -->
MANDADO DE PENHORA
Processo 9001087-60.2022.8.26.0390
Executado: MARCOS PEREIRA, CPF 529.982.247-25
Valor: R$ 12.500,00 em 10/03/2024
Exequente: ANA LIMA, CPF 111.444.777-30
```

`to_markdown(annotated=True)` acrescenta o que um modelo precisa para citar:

```text
<!-- documento · PDF 1.4 -->
<!-- página 0 · text_layer -->
[p0:0] MANDADO DE PENHORA
[p0:1] Processo 9001087-60.2022.8.26.0390
[p0:2] Executado: MARCOS PEREIRA, CPF 529.982.247-25
[p0:3] Valor: R$ 12.500,00 em 10/03/2024
[p0:4] Exequente: ANA LIMA, CPF 111.444.777-30
<!-- decisão: sem evidência de falha -->
- CNJ: 9001087-60.2022.8.26.0390 · confirmed · p0:1
- CPF: 529.982.247-25 · confirmed · p0:2
- valor em reais: R$ 12.500,00 · well_formed · p0:3
- data: 10/03/2024 · well_formed · p0:3
- CPF: 111.444.777-30 · failed (impresso assim: text_layer) · p0:4
```

A primeira linha resume `Result.document`: a versão do PDF, o programa que o
gravou, quantas assinaturas ele declara e quantas vezes foi gravado. Cada
parte só aparece quando há o dado, e aqui só a versão aparece. O comentário de
cada página ganha o código da tarja e a folha, quando a página os tem. Cada
linha começa pela referência dela. Depois do texto vêm o motivo da decisão e
as entidades com estado e referência. Vêm também as linhas com mais de um
valor do mesmo tipo, os blocos do detector de layout e as figuras. `furniture=False` tira das
duas formas o cabeçalho, o rodapé e a tarja.

A forma anotada é o que se entrega a um modelo de linguagem. A referência é
curta, e o modelo a copia sem erro. Ela leva ao trecho, e o trecho leva à
página, à caixa, ao leitor e à confiança. Como conferir o que o modelo cita
está em [Entregar a leitura a um agente](../agent.md).
