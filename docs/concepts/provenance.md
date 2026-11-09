# Origem e cache

Cada [trecho](../glossary.md#trecho) do resultado diz de onde veio: a
página, a caixa, o leitor e a ordem de leitura. O resultado inteiro diz com
que leitores e versões foi feito. O cache guarda as leituras com uma chave
que muda sempre que a leitura pode mudar.

## O que cada trecho carrega

```python
import docaudit

result = docaudit.process("documento.pdf", cheap=["text_layer"])
pages = {p.index: p for p in result.pages}
for c in result.chunks:
    dims = pages[c.page].dimensions
    px = c.bbox.to_pixels(dims.width_px, dims.height_px)
    print(c.page, px, c.source, c.confidence, c.reading_order, c.text[:50])
```

**O texto como lido.** `Chunk.text` é o que o leitor devolveu, sem
correção. A camada de texto sai em NFC, a forma composta do Unicode. As
verificações procuram a forma impressa num texto em que hífens, espaços e
formas de largura total tipográficos viram ASCII. Essa troca não muda a
posição de nenhum caractere.

**Caixas normalizadas.** A [caixa](../glossary.md#caixa) vai de 0 a 1, com
origem no canto superior esquerdo. Ela não guarda pixels. Uma caixa em
pixels só tem sentido junto do DPI em que a página foi renderizada, e esse
par se separa na primeira serialização. `to_pixels()` e `from_pixels()`
convertem na borda, onde o DPI ainda está à mão. O formato está em
[Campos do resultado](../response/fields.md#chunk).

**Identificador por conteúdo.** O `Chunk.id` é determinístico. O mesmo
documento, com os mesmos leitores, gera os mesmos identificadores, com ou
sem cache e em qualquer máquina. Entram no hash:

- o hash do documento e o DPI;
- o índice da página, porque um documento pode ter duas páginas de bytes
  idênticos;
- a caixa e o leitor;
- o texto inteiro, porque dois trechos podem ocupar a mesma caixa no mesmo
  motor, como uma célula e a linha que a contém.

Nenhum pixel entra: o documento e o DPI já determinam a renderização.

## A execução

`Result.run` diz com que política, leitores e argumentos o resultado saiu.
Em `Run.versions` está a versão de cada leitor que leu alguma linha: pesos,
motor, dispositivo, idioma e prompt. A chave é o `source` do trecho.

A versão fica ao lado do identificador, e não dentro dele. Assim a citação
de uma linha sobrevive a uma troca de pesos que não mudou a leitura. Com o
PDF e o `Result` em JSON guardados, a leitura pode ser refeita, e qualquer
recorte sai de novo de `Document.crop`. Ver
[Guardar a leitura para treinar](../recipes/training-pairs.md).

## A leitura que saiu

Quando a releitura por outra [família](../glossary.md#familia) ou o
[leitor caro](../glossary.md#leitor-caro) substitui uma linha
por outro texto, a linha que saiu fica em `Result.others`, com `replaced`,
ao lado da que entrou. Ficam ali também:

- a releitura recusada no lugar de uma linha que falha, ao lado da linha
  que continuou;
- numa digitalização com camada de OCR, a linha da camada que lê outro
  valor em reais, com `check` e `value`.

Duas coisas saem sem deixar linha em `Result.others`:

- a linha mal decodificada fora das caixas do leitor caro, que é lixo por
  definição;
- a linha cara recusada longe de um valor que falhou. Ela aparece em
  `RoutingDecision.steps` e em `spent.lines_strong_rejected`.

## O que o arquivo diz de si

`Result.document` traz o produtor, as datas, a versão do PDF, as
assinaturas declaradas e quantas vezes o arquivo foi gravado.
`Page.hidden_fonts` traz as fontes do texto escondido de cada página.

Esses campos provam menos do que parecem:

- O `producer` é de quem gravou o arquivo por último, e não de quem o
  criou. Um PDF dividido em páginas por uma ferramenta de tribunal ou de
  raspagem sai com o nome dessa ferramenta. Sai sem assinatura, e às vezes
  sem data e sem `/ID`. `saves` e `identifier_changed` são o rastro dessa
  regravação.
- As fontes do texto escondido sobrevivem à divisão. Elas dizem qual motor
  escreveu a camada de OCR de uma digitalização, sem que a biblioteca nomeie
  motor nenhum. O Tesseract deixa `GlyphLessFont`; um montador de PDF deixa
  as fontes base do PDF.
- A assinatura é lida como o arquivo a declara, sem conferir a
  criptografia.

O que esses campos dizem com segurança vai no sentido oposto. Um documento
inteiro, assinado e com `saves` igual a 1 chegou como saiu de quem o
emitiu.

## Cache

`ModelCallCache` guarda a leitura de cada página por cada leitor. Guarda as
duas etapas, a releitura por outra família e a detecção de layout.

```python
from pathlib import Path

import docaudit
from docaudit import ModelCallCache

cache = ModelCallCache(Path(".cache/docaudit.sqlite"))
result = docaudit.process("documento.pdf", cache=cache)
```

Sem caminho, o cache grava em `calls.sqlite` dentro de
`DOCAUDIT_CACHE_DIR`, ou de `~/.cache/docaudit` sem a variável. Vários
processos do sistema operacional podem partilhar o mesmo arquivo.

A chave tem estes componentes:

| componente | por quê |
|---|---|
| hash do documento, índice da página, DPI | a entrada: juntos determinam os pixels |
| caixa do recorte, quando o leitor lê um | um recorte da página é outra leitura |
| nome do leitor | quem leu |
| `output_version` do leitor | pesos, idioma, prompt e formato do que ele produz |
| digest do esquema de `Chunk` | a forma do que está guardado |

Nenhum pixel entra na chave. Consultar o cache não custa uma renderização,
e a camada de texto continua sem renderizar. Duas páginas de bytes
idênticos não partilham a entrada, porque o índice da página entra.

A versão e o digest evitam a falha silenciosa. Sem eles, uma entrada gravada
num formato continuaria sendo lida depois de o formato mudar, e o Pydantic
preencheria o que falta com o valor padrão. O digest sai dos campos do
próprio `Chunk`, e por isso muda sem que alguém precise lembrar de
atualizá-lo.

O cache guarda o texto dos documentos em claro. O cuidado com o arquivo
está em [Segurança dos dados](../security.md#o-que-fica-no-disco).
