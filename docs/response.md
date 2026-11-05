# Formato da resposta

`process()` e `Document.read()` devolvem um `Result`. É um modelo Pydantic
congelado: `result.model_dump_json()` serializa tudo, e
`Result.model_json_schema()` descreve o formato em JSON Schema.

## Exemplo

Um PDF de uma página, nato-digital, lido só pela camada de texto com a
política `evidence`. A saída abaixo é real, com `spent` encurtado e as caixas arredondadas a
quatro casas.

```python
import docaudit
from docaudit import Budget

result = docaudit.process(
    "edital.pdf", policy="evidence", budget=Budget(max_strong_pages=1), cheap=["text_layer"]
)
print(result.model_dump_json(indent=2))
```

```json
{
  "doc_id": "d9921efc17945faf",
  "pages": [
    {
      "doc_id": "d9921efc17945faf",
      "index": 0,
      "dimensions": {"width_pt": 595.0, "height_pt": 842.0, "width_px": 1653, "height_px": 2339, "dpi": 200},
      "substrate": "born_digital",
      "substrate_evidence": {
        "chars": 54.0, "visible_text": 2.0, "invisible_text": 0.0, "covered_text": 0.0, "unmapped_text": 0.0, "unread_regions": 0.0
      },
      "stamp": null,
      "folha": null,
      "unread": []
    }
  ],
  "chunks": [
    {
      "id": "c10109f0af26789d6342cad1",
      "page": 0,
      "bbox": {"x0": 0.1234, "y0": 0.0818, "x1": 0.4556, "y1": 0.0976},
      "text": "EDITAL DE CONVOCAÇÃO",
      "source": "text_layer",
      "confidence": null,
      "reading_order": 0,
      "kind": null
    },
    {
      "id": "6323c9c0fc99345c618da7de",
      "page": 0,
      "bbox": {"x0": 0.1224, "y0": 0.1236, "x1": 0.4346, "y1": 0.1332},
      "text": "Processo 9001087-60.2022.8.26.0390",
      "source": "text_layer",
      "confidence": null,
      "reading_order": 1,
      "kind": null
    }
  ],
  "decisions": [
    {
      "page": 0,
      "tier": "cheap",
      "reason": "sem evidência de falha",
      "signals": {},
      "steps": ["tier barato: text_layer leu 2 linha(s)", "política: sem evidência de falha"],
      "failures": [],
      "incomplete": false
    }
  ],
  "spent": {"pages_total": 1, "pages_cheap": 1, "pages_strong": 0, "seconds_cheap": 0.0002, "seconds": 0.0093},
  "run": {
    "started_at": "2026-10-20T02:35:59.000357Z",
    "policy": "evidence",
    "budget": {"max_strong_pages": 1, "max_strong_fraction": null},
    "cheap": ["text_layer"],
    "confirm": null,
    "strong": null,
    "reread": "page",
    "trust_layer": "visible",
    "dpi": null,
    "entities": ["CPF", "CNPJ", "CNJ", "valor em reais", "valor em moeda anterior ao real", "data", "data com dia da semana", "data por extenso", "folha", "chave de acesso", "linha digitável de boleto", "código de arrecadação"],
    "versions": {"text_layer": "3:pypdfium2=5.14.0"}
  },
  "library_version": "0.0.1.dev55+ge5f79c2bf"
}
```

Uma página escalada pela política tem esta decisão. O leitor barato leu um CPF
com dígito verificador errado, e o leitor caro leu a página inteira:

```json
{
  "page": 0,
  "tier": "strong",
  "reason": "1 x CPF que falha a verificação",
  "signals": {"CPF que falha a verificação": 1},
  "steps": [
    "tier barato: barato leu 1 linha(s)",
    "política: 1 x CPF que falha a verificação",
    "caro leu a página inteira: 1 linha(s); substituiu 1 da leitura barata, ficaram 0"
  ]
}
```

## `Result`

| campo | tipo | o que traz |
|---|---|---|
| `doc_id` | `str` | 16 dígitos hexadecimais do SHA-256 dos bytes do documento |
| `pages` | `tuple[Page, ...]` | as páginas processadas, na ordem do documento |
| `chunks` | `tuple[Chunk, ...]` | o texto lido, página a página |
| `decisions` | `tuple[RoutingDecision, ...]` | uma decisão por página |
| `entities` | `tuple[Entity, ...]` | cada valor com forma e regra achado nas linhas, com estado; ver abaixo e [Entidades](entities.md) |
| `others` | `tuple[OtherReading, ...]` | as outras leituras do lugar de uma linha: a que não a substituiu e a que saiu por ela; ver abaixo |
| `spent` | `Spent` | o que a execução gastou; ver abaixo |
| `run` | `Run` ou `null` | com que leitores, em que versão e com que argumentos o resultado saiu; ver abaixo |
| `document` | `DocumentFacts` ou `null` | o que o arquivo diz de si: produtor, datas, versão, assinaturas, gravações; ver abaixo |
| `library_version` | `str` | a versão do pacote que gerou o resultado |

Seis métodos dão as outras formas de uso:

- `result.read_by()` diz, por página, os leitores que deram linhas. A folha
  digitalizada sob uma tarja de texto é `born_digital`, e o corpo vem dos pixels;
- `result.verification()` conta, por página e por verificação, os valores em
  cada estado, e em `printed` as falhas impressas no documento;
- `result.by_page()` devolve `dict[int, list[Chunk]]`, cada lista na ordem de
  leitura. Um trecho sem `reading_order` vai ao fim, de cima para baixo.
- `result.refs()` devolve `dict[str, Chunk]`: uma referência curta por
  linha, `p<página>:<posição>`, na ordem de leitura, para citar a linha.
- `result.figures()` devolve as imagens das páginas compostas, cada uma com
  as linhas lidas dentro dela; ver abaixo.
- `result.to_markdown()` devolve o texto, uma linha por trecho, com um
  comentário HTML por página que diz o índice e quem leu. `annotated=True`
  acrescenta ao comentário o documento e a folha, com a referência das linhas
  de onde vieram, põe a referência no início de cada linha e fecha cada página com a
  decisão, as entidades e as figuras dela; `furniture=False` tira cabeçalho, rodapé e
  tarja. É a forma de entregar o documento a um modelo: ver
  [Análise por um agente](agent.md).

```text
<!-- página 0 · text_layer -->
[p0:0] EDITAL DE CONVOCAÇÃO
[p0:1] Processo 9001087-60.2022.8.26.0390
<!-- decisão: sem evidência de falha -->
- CNJ: 9001087-60.2022.8.26.0390 · confirmed · p0:1
```

## O mesmo documento em três formas

Cada forma serve a um consumidor, e as três apontam para o mesmo `Chunk`:

| forma | para quem | como se chega à origem |
|---|---|---|
| `result.model_dump_json()` | um programa, um banco, uma ferramenta de revisão | `Chunk.id`, estável entre execuções; página e caixa no próprio chunk |
| `result.to_markdown()` | busca, leitura humana, um índice | o cabeçalho de página |
| `result.to_markdown(annotated=True)` | um modelo de linguagem | a referência `p<página>:<posição>`, por `result.refs()` |

A forma anotada é o contrato com o agente. Cada linha tem uma referência
curta que o modelo copia sem erro, e a referência leva ao chunk, à página,
à caixa, ao leitor e à confiança. Ao fim de cada página vêm a decisão da
cascata, as entidades com estado e as figuras. O que o modelo afirmar sem
uma referência que confira não tem origem, e é descartado: ver
[Análise por um agente](agent.md#conferir-a-citacao-sem-modelo).

### Ao lado de outras ferramentas

Os nomes mudam; a forma é a mesma das ferramentas de parsing de 2026. Uma
lista de blocos com página e caixa normalizada, um identificador por
bloco, o texto em markdown, e o markdown ligado aos blocos pelo
identificador.

| o que | docaudit | Landing AI ADE | Docling | Reducto | Mistral OCR |
|---|---|---|---|---|---|
| bloco com texto | `Chunk`, uma linha ou uma região | `chunks[]` | `texts[]`, `tables[]` | `blocks[]` dentro de `chunks[]` | `pages[].markdown` |
| página e caixa | `page`, `bbox` em `[0, 1]`, origem no alto à esquerda | `grounding.page`, `grounding.box` em `[0, 1]` | `prov.page_no`, `prov.bbox` | `bbox` em `[0, 1]`, com `page` | caixa por imagem e, no OCR 4, por bloco |
| identificador | `Chunk.id`, do conteúdo e da posição | `id`, um UUID | `self_ref`, um ponteiro JSON | não há um estável | `id` da imagem |
| tipo do bloco | `kind`, quando há detector de layout | `type`: text, table, figure, logo... | `label` | `type` | rótulo do bloco, no OCR 4 |
| markdown ligado ao bloco | `[p3:12]` em `to_markdown(annotated=True)` | âncora `<a id=...>` antes de cada chunk | exportação, sem âncora | `content` por chunk | não |
| confiança | `confidence`, crua, do motor | `confidence` e `low_confidence_spans` | não | `high`/`low`, ou número | por página ou palavra, no OCR 4 |
| cabeçalho e rodapé | `furniture`, sem apagar | `marginalia` | árvore `furniture` | tipo `Header`/`Footer` | campos de cabeçalho e rodapé, no OCR 4 |
| figura | `figures()`, com as linhas lidas nela | chunk `figure` | `pictures[]` | bloco `Figure` | `images[]`, com a imagem em base64 |
| quem leu cada bloco | `source` | não | não | não | não |
| se o valor confere | `Entity.state` | não | não | não | não |
| por que a página foi relida | `RoutingDecision.reason` e `steps` | não | não | não | não |
| o que custou | `Spent`, por etapa, sem o que o cache serviu | `credit_usage` | não | uso na conta | uso na conta |

As quatro últimas linhas são o que a biblioteca acrescenta. As faltas estão
em [Limites](limits.md): célula de tabela, confiança por palavra e
hierarquia de seções. Os nomes de campo de terceiros foram conferidos nas
documentações deles em outubro de 2026, e mudam entre versões: a Landing AI
na [resposta do ADE](https://docs.landing.ai/ade/ade-json-response), o
Docling no [modelo do documento](https://docling-project.github.io/docling/concepts/docling_document/),
a Reducto no [formato da resposta](https://docs.reducto.ai/parse/response-format).

## `Page`

| campo | o que traz |
|---|---|
| `index` | índice da página, a partir de zero |
| `dimensions` | largura e altura em pontos e em pixels, e o DPI da renderização; `dimensions.paper` diz `A4`, `Letter`, `Ofício` ou `None`, com 3 mm de folga |
| `substrate` | `born_digital`, `searchable_scan` ou `image_only`; ver [Conceitos](concepts.md#substrato) |
| `substrate_evidence` | os números que decidiram o substrato: `chars`, `visible_text`, `invisible_text`, `covered_text`, `unmapped_text`, `unread_regions` e, quando há imagem, `native_dpi` |
| `stamp` | a tarja da camada de texto (`Stamp`), num dos formatos de `stamps=`; na página copiada de outro processo, a última desenhada; `null` sem tarja. Ver abaixo |
| `folha` | a folha dos autos carimbada na página (`Folha`): `value`, e a caixa e a linha do carimbo; `null` sem carimbo. Ver abaixo |
| `unread` | caixas das imagens e dos desenhos que nenhuma camada de texto leu, de cima para baixo e da esquerda para a direita; o índice é o que `region` de um trecho aponta |
| `hidden_fonts` | os nomes base das fontes do texto invisível, sem repetição: quem escreveu a camada de uma digitalização. O Tesseract deixa `GlyphLessFont`; um montador de tribunal, as fontes base do PDF. Vazio numa página composta |

### A tarja e a folha

| campo de `stamp` | o que traz |
|---|---|
| `format` | o nome do `StampFormat` que casou: `e-saj` por omissão; ver [a tarja de outro sistema](recipes.md#a-tarja-e-a-folha-de-outro-sistema) |
| `code` | o código de conferência: o id da peça juntada. Muda onde começa outra peça |
| `process` | o número do processo que a tarja cita, como impresso |
| `signer` | quem assinou, como impresso |
| `at` | quando a peça foi protocolada ou liberada nos autos: a hora local impressa, sem fuso |
| `protocol` | o número do protocolo; no e-SAJ, `null` no ato liberado nos autos pelo juízo |
| `bbox`, `chunk_ids` | a caixa e as linhas da tarja |

Fora `code`, um campo que o formato não imprime sai `null`.

`folha.value` é o valor de `FOLHA` numa linha de elemento fixo; no corpo, a
mesma forma é citação e fica só em `entities`. `folha` é `null` sem carimbo,
no verso e numa execução de uma página só. Um documento juntado com
numeração própria, sem o carimbo do tribunal na camada, sai com a numeração
dele, e `folha.in_sequence` o aponta: é `true` quando a folha menos o índice
da página é a diferença mais comum da execução. Num PDF que junta peças de
vários processos, quase nenhuma folha segue a sequência.

A tarja cujo número de processo não confere no dígito do CNJ não é tarja;
um formato sem CNJ desliga a conferência com `process_check=None`.

Todo valor do resultado traz a página, a caixa e as linhas de onde saiu
(`bbox`, `chunk_ids`), e `Document.crop(page, bbox)` recorta o lugar. A ordem
das linhas está em [Conceitos](concepts.md#ordem-de-leitura-por-layout).

## `Chunk`

| campo | o que traz |
|---|---|
| `id` | identificador determinístico; ver abaixo |
| `page` | índice da página, como em `Page.index` |
| `bbox` | a caixa do trecho, normalizada |
| `text` | o texto como o leitor o devolveu, com as quebras de linha |
| `source` | o nome do leitor que produziu o trecho |
| `confidence` | a confiança média que o motor deu, em `[0, 1]`, ou `null` |
| `reading_order` | a posição do trecho na ordem de leitura da página, ou `null` |
| `turn` | os graus, no sentido anti-horário, que o leitor girou a página para ler a linha em pé: `0`, `90` ou `270`. A caixa não gira e segue [a convenção de sempre](#a-caixa) |
| `kind` | o tipo da região de onde o texto veio (`text`, `table`, `paragraph_title`...), quando um detector de layout o deu |
| `line_break_hyphens` | índices em `text` dos hífens que estavam numa quebra de linha do PDF, na camada de texto; o hífen fica no texto, e juntar as metades é de quem lê |
| `region` | índice em `unread` da página do raster de onde a linha veio, quando um leitor de pixels a leu num raster que a camada de texto não leu; `null` nos outros casos |
| `furniture` | `true` na linha que se repete, no mesmo lugar, em outra página lida, numa sequência a partir da borda da folha ou na vertical da margem: o cabeçalho, o rodapé, a tarja. A linha fica no resultado |

A unidade depende do leitor. A camada de texto, o Tesseract e o PP-OCR
devolvem uma linha por trecho. O leitor `vlm` com detector de layout devolve
uma região por trecho; sem detector, a página inteira num trecho. Uma tabela
lida pelo `vlm` vem num trecho só, uma linha de texto por linha da tabela,
com as células separadas por ` | `.

`confidence` é um sinal cru do motor. A escala muda de um motor para outro, e
a biblioteca não aplica limiar sobre ela.

### A caixa

`BBox` guarda `x0, y0, x1, y1` em `[0, 1]`, com origem no canto superior
esquerdo da página como ela é exibida, já com o `/Rotate` do PDF aplicado. É a
convenção da Landing AI ADE. A primeira página é a de índice 0, em `page` e em
`Page.index`. A
caixa não guarda pixels. Para recortar uma imagem, converta na hora, com o
tamanho da imagem que você tem:

```python
x0, y0, x1, y1 = chunk.bbox.to_pixels(image.width, image.height)
```

`BBox.from_pixels(x0, y0, x1, y1, width_px=..., height_px=...)` faz o
caminho inverso, para um leitor que recebe caixas em pixels do motor. Os
pontos de PDF saem de `Page.dimensions.width_pt` e `height_pt`.

### O identificador

`Chunk.make_id` é o SHA-256 de cinco coisas: o `doc_id` com o DPI, o índice
da página, a caixa, o nome do leitor e o texto. O mesmo documento, lido pelos
mesmos leitores, gera os mesmos ids em qualquer ambiente. O texto entra porque dois trechos podem ocupar
a mesma caixa. O índice entra porque um documento pode ter duas páginas de
bytes idênticos.

## `Entity`

| campo | o que traz |
|---|---|
| `kind` | o nome do campo: `CPF`, `CNPJ`, `CNJ`, `valor em reais`, `data`, ou o nome de um `Check` seu |
| `value` | o valor como impresso, com os espaços colapsados |
| `state` | `confirmed`, `well_formed` ou `failed`; o que cada um prova está em [Entidades](entities.md#os-tres-estados) |
| `page` | índice da página |
| `bbox` | a menor caixa que contém as linhas do valor |
| `chunk_ids` | os `id` das linhas que o valor toca, duas quando ele quebra entre linhas |
| `span` | com `spans=True`, o começo e o fim do valor no texto das linhas de `chunk_ids` unidas por quebra de linha; `null` por omissão |
| `printed` | num `failed`, a prova de que o erro é do documento; ver [Entidades](entities.md) |

```json
{
  "kind": "CPF",
  "value": "529.982.247-26",
  "state": "failed",
  "page": 0,
  "bbox": {"x0": 0.1224, "y0": 0.1236, "x1": 0.4346, "y1": 0.1332},
  "chunk_ids": ["6323c9c0fc99345c618da7de"],
  "printed": "tesseract"
}
```

## `Figure`

Uma imagem numa página composta: a planta, a foto, o print, a tabela colada
como imagem. Não é campo do `Result`: sai de `result.figures()`, a partir
de `Page.unread` e do `Chunk.region` de cada linha. Numa página
digitalizada a folha inteira é imagem, e ela não é figura.

| campo | o que traz |
|---|---|
| `ref` | `p<página>:f<índice>`, o nome com que um modelo cita a figura |
| `page` | índice da página |
| `index` | o índice da imagem em `Page.unread` |
| `bbox` | a caixa da imagem |
| `chunk_ids` | as linhas que um leitor de pixels leu dentro dela; vazio numa foto ou assinatura sem texto |

`Document.crop(figure.page, figure.bbox)` devolve o PNG da figura, no DPI
em que os leitores a viram.

## `OtherReading`

A mesma área da folha lida por dois leitores. Sai em `result.others`, e
`Document.doubts()` junta a de cada linha à dúvida dela.

| campo | o que traz |
|---|---|
| `line` | o `id` da linha do resultado |
| `reading` | o `Chunk` do outro leitor, com caixa, texto e `source` |
| `same` | o outro leitor leu o mesmo valor inválido: duas famílias apontam o erro impresso |
| `replaced` | `reading` estava no resultado e saiu com outro texto: `line` é a linha que entrou no lugar dela |
| `check`, `value` | numa linha que não falha, o campo e o valor que a outra família lê diferente |

Há três casos. A releitura que não conferiu fica ao lado da linha que
continuou no resultado. A linha da camada de OCR que lê outro valor em
reais também, com `check` e `value`. A leitura que saiu com outro texto,
porque a releitura por outra família conferiu ou porque o leitor caro leu
ali, fica ao lado da linha que a substituiu, com `replaced`. Com o leitor
caro lendo a página inteira num trecho só, essas linhas apontam a esse
trecho. `Document.doubts()` deixa as substituídas de fora.

## `RoutingDecision`

| campo | o que traz |
|---|---|
| `page` | índice da página |
| `tier` | `cheap` ou `strong`: o destino que a política deu à página |
| `reason` | a frase do motivo, para quem lê |
| `signals` | a contagem de cada sinal que disparou, pelo nome do sinal |
| `steps` | o que `process` fez com a página, uma frase por passo, na ordem |
| `failures` | cada leitor que falhou na página, como `<leitor>: <mensagem>`: o da cascata que deu a vez ao seguinte, o da releitura, o caro; vazio quando nenhum falhou |
| `incomplete` | um leitor falhou e nenhum outro leu no lugar: as linhas, se houver, são só parte da página. Falso se o seguinte da cascata leu, e se só o caro falhou |

`tier` é o veredito da política. Sem leitor caro (`strong=None`), uma página pode
estar em `strong` e ter sido lida só no tier barato: é o modo de ensaio de uma
política. `spent.pages_strong` conta o que de fato rodou.

## `spent`

O que a chamada gastou, relatado e não limitado. Todas as chaves abaixo saem
sempre, zeradas quando a etapa não rodou.

| chave | o que conta |
|---|---|
| `pages_total` | páginas processadas |
| `pages_cheap` | páginas lidas no tier barato |
| `pages_cheap_cached` | dessas, as que vieram do cache |
| `pages_cheap_failed` | páginas em que algum leitor barato falhou e deu a vez ao seguinte |
| `regions_cheap` | páginas em que o leitor seguinte da cascata leu, como região, as imagens que a camada de texto não leu |
| `pages_strong` | páginas lidas pelo leitor caro |
| `pages_strong_cached` | dessas, as que vieram do cache |
| `pages_strong_failed` | páginas que o leitor caro recusou e ficaram com a leitura barata |
| `regions_strong` | páginas em que o leitor caro leu só a região das linhas que falharam |
| `lines_strong_rejected` | linhas do leitor caro que não entraram no lugar das baratas: perderam um valor que conferia, ou não explicaram o valor que falhou |
| `pages_confirmed` | páginas relidas por outra família antes do leitor caro |
| `pages_confirmed_same` | dessas, as que voltaram com o mesmo valor inválido: erro do documento |
| `pages_confirmed_fixed` | dessas, as que voltaram com o valor que confere no mesmo lugar |
| `pages_confirm_cached` | releituras que vieram do cache |
| `pages_layout_cached` | detecções de layout que vieram do cache |
| `seconds_cheap`, `seconds_confirm`, `seconds_strong` | tempo de parede de cada etapa; a detecção de layout entra na etapa que renderizou a página |
| `seconds` | segundos da chamada inteira |

Um leitor que implementa `Metered`, como o `vlm`, acrescenta `calls`,
`tokens_in`, `tokens_out` e, quando recebeu preços, `usd`. Contam o leitor
caro, os baratos e o de `confirm=`. O valor é a diferença entre o início e o
fim da chamada: o que o cache serviu não conta. A biblioteca não traz tabela
de preços, porque o número é de quem chama e envelhece.

## `document`

O que o arquivo diz de si, lido do trailer, do catálogo e do dicionário de
informações, sem renderizar nada. `process` sempre o preenche; `null` só
num resultado gravado por uma versão anterior. `docaudit.pdf.load_facts`
devolve o mesmo sem ler página nenhuma, e `Document.facts` o guarda.

| campo | o que traz |
|---|---|
| `producer`, `creator` | quem gravou o arquivo por último e o programa que o criou, ou `null` |
| `title`, `author`, `subject`, `keywords` | os campos do `/Info`, ou `null` |
| `created_at`, `modified_at` | as datas do `/Info`, com o fuso que o arquivo declara |
| `pdf_version` | `1.4`, `1.7`; `null` quando o arquivo não a declara |
| `tagged` | se o PDF tem árvore de estrutura: a ordem de leitura é declarada |
| `form` | `none`, `acroform`, `xfa_full` ou `xfa_foreground` |
| `saves` | quantas vezes o arquivo foi gravado, pelos `startxref`: um na criação, mais um por atualização incremental; o trailer extra de um arquivo linearizado não conta. `null` sem o arquivo, como numa imagem |
| `identifier_changed` | se o `/ID` mutável difere do permanente: o arquivo foi regravado. `null` sem `/ID` |
| `restricted` | se o arquivo nega alguma permissão, como copiar texto |
| `page_labels` | se o arquivo declara rótulos de página próprios |
| `signatures` | as assinaturas digitais declaradas (`Signature`): `sub_filter`, `signed_at`, `reason`, `mdp_permission` e `covers_file` |

O que estes campos provam, e o que não provam, está em
[Conceitos](concepts.md#proveniencia). Uma assinatura é lida como declarada:
o pdfium não confere a criptografia, e o signatário fica no pacote PKCS#7,
que a biblioteca não abre. `covers_file` diz se o `/ByteRange` chega ao fim
do arquivo, isto é, se nada foi gravado depois dela.

## `run`

Com que leitores, em que versão e com que argumentos o resultado saiu. É o
que basta para refazer a leitura, e para saber depois que pesos, motor e
dispositivo leram cada linha. `process` sempre o preenche; `null` só num
resultado gravado por uma versão anterior a ele. As páginas lidas estão em
`pages` do resultado.

| campo | o que traz |
|---|---|
| `started_at` | o início da execução, em UTC |
| `policy` | o nome da política de triagem |
| `budget` | o teto de páginas do leitor caro |
| `cheap` | os leitores da cascata barata, na ordem |
| `confirm`, `strong` | o leitor da releitura por outra família e o caro, ou `null` |
| `reread`, `trust_layer`, `dpi` | os argumentos de mesmo nome de `process` |
| `entities` | os nomes das verificações de `entities`, na ordem |
| `versions` | o `output_version` de cada leitor que leu alguma linha do resultado, pelo nome, e o do detector de layout em `layout` |

`versions` é a ponte entre a linha e o modelo: o `source` de cada trecho, e o
de cada leitura em `others`, é uma chave dele. A versão é a mesma que entra
na chave do cache, e diz o que muda a leitura sem mudar o nome do leitor:

| leitor | o que a versão traz |
|---|---|
| `text_layer` | a versão do pypdfium2 |
| `tesseract` | o binário, o idioma e a configuração |
| `ppocr` | os pesos, ou o hash do reconhecedor próprio e do dicionário, a versão do RapidOCR e o motor quando não é o ONNX Runtime na CPU |
| `vlm` | o modelo servido, o preset, o detector de layout e o esforço de pensamento |

O `Chunk.id` não leva a versão: o mesmo texto, na mesma caixa, pelo mesmo
leitor, tem o mesmo id em qualquer versão, e a citação de uma linha
sobrevive a uma troca de pesos que não mudou a leitura. A versão vai ao
lado, aqui. Dois leitores de mesmo nome em papéis diferentes, como dois
`PPOCR` em motores diferentes, não se distinguem pela linha; `versions`
guarda a do primeiro.

Um leitor que não leu nenhuma linha do resultado não entra em `versions`:
a versão de um `vlm` sem `served=` pergunta ao servidor, e um leitor caro
que nunca foi chamado não paga essa pergunta. Ele continua em `strong` ou
`confirm`, pelo nome.
