# Limites

Esta página lista o que o `docaudit` não faz e os comportamentos que você
precisa conhecer antes de confiar num resultado.

## O que não faz

- **Tabela como células.** A tabela sai como linhas. As células vêm
  separadas por ` | ` quando o leitor `vlm` leu a tabela, e sem separador
  quando a leitura foi da [etapa barata](glossary.md#etapa-barata). `Result.records()` junta em fileiras
  as linhas lado a lado, e em blocos as fileiras vizinhas, só pela posição
  das caixas. Não há coluna, cabeçalho nem célula mesclada. Montar a tabela
  a partir disso fica com quem usa a biblioteca.
- **Extração de campos por esquema.** A biblioteca devolve texto com a
  origem de cada [trecho](glossary.md#trecho). Ela não preenche um esquema de campos. Um valor
  extraído fica ligado à caixa do trecho, e não a uma caixa menor.
- **Confiança por palavra.** O trecho é a linha, ou a região, e a confiança
  é a média dela.
- **Carimbos lidos pelo leitor por região.** O detector de layout descarta
  por padrão as regiões rotuladas como texto lateral, rodapé, nota de
  rodapé, cabeçalho, imagem, número de folha e carimbo (`DROP_DEFAULT`). O
  leitor `vlm` não as lê. As linhas delas ficam da leitura barata, quando o
  OCR (reconhecimento óptico de caracteres) barato as leu.
- **Rotação do conteúdo.** O `/Rotate` do arquivo é aplicado, e o PP-OCR lê
  em pé a página digitalizada de lado (`Chunk.turn`). O [leitor caro](glossary.md#leitor-caro) vê em pé
  a página que a leitura barata leu de lado. Na cascata barata, em
  `confirm=` e em `Document.reread`, os outros leitores veem a imagem como
  ela é. Uma página digitalizada de cabeça para baixo não é detectada.
- **Consistência entre páginas.** Os sinais veem uma página por vez.
  Conferir que o número do processo é o mesmo em todas as páginas exige
  olhar o documento inteiro. Para isso não há gancho além de uma política
  própria.
- **Tipo de cada [peça](glossary.md#peca).** `Result.pieces()` agrupa as páginas seguidas com a
  mesma [tarja](glossary.md#tarja). Dizer se a peça é petição, decisão ou certidão fica com quem
  lê.
- **Exportação além de JSON e Markdown simples.** Não há DocTags, HTML de
  documento nem formato de layout.
- **Manuscrito.** Os leitores da cascata leem texto impresso. Numa página
  manuscrita, todos eles erram muito, e o PP-OCR maior não muda isso. As
  verificações continuam valendo para o que foi lido, mas quase nada sai com
  a forma de um campo, e uma página sem valor `failed` não foi conferida.
- **Foto de celular.** A página fotografada, com perspectiva, sombra e dobra,
  é lida com mais erro que a digitalizada. O Tesseract cai muito mais que o
  PP-OCR nesse caso. Com `confirm=` no Tesseract, a releitura tende a não
  resolver o valor que falhou numa foto, e a página segue para o leitor
  caro. O PP-OCR maior não lê a foto melhor que o padrão.
- **Idioma por página.** O idioma do OCR é um só por chamada.
- **API assíncrona.** `process()` é síncrono. Num servidor assíncrono,
  rode-o numa thread ou num processo à parte.

## Comportamentos conhecidos

- **O valor que perde a forma não é verificado.** Uma verificação só olha o
  texto que casa com a forma impressa do campo. Um CNPJ que a leitura
  devolveu sem a barra, um `R$` lido como `R5`, um número de processo que
  sumiu de uma tarja inclinada: nenhum casa e nenhum vira entidade. Nenhum
  sinal dispara por eles, e a página não é encaminhada. Uma página sem valor
  `failed` não é uma página conferida. Quem precisa de um campo em toda
  folha confere a presença dele com `Result.entities` e `Page.stamp`.
- **Um valor errado pode passar no dígito verificador.** O dígito prova que
  o valor é possível, não que é o impresso. No CPF e no CNPJ, que escrevem o
  resto 10 como 0, a troca de um só dígito passa em alguns casos. No número
  de processo, em módulo 97, nenhuma troca de um dígito passa, mas duas
  trocas podem passar. O estado `confirmed` é evidência forte, não prova.
- **Um servidor `vlm` local ausente interrompe o documento.** Quando a
  conexão é recusada num servidor da própria máquina, o leitor levanta
  `ConnectionError`. O servidor não está lá, e repetir não o traz. Num
  servidor [externo](glossary.md#externo), a mesma recusa é uma falha passageira.
- **`VLM(retries=)` repete as falhas passageiras, em qualquer servidor.**
  O 429, o 5xx, o tempo esgotado e a conexão caída são repetidos `retries`
  vezes. Depois disso a página falha e fica com a leitura barata. O padrão
  é `0`. Com `cache`, a segunda execução retoma do que já foi lido.
- **Uma resposta cortada no teto de tokens falha a página.** É o caso de
  um modelo que entra em laço de repetição. A página fica com a leitura
  barata.
- **O leitor `vlm` sem detector devolve a página como um trecho só.** A
  caixa cobre a página inteira, a página tem uma referência só em
  `Result.refs()`, e `Document.crop` dessa caixa é a página inteira. A
  linha, com a sua caixa, vem com `reread="region"` ou com `layout=`.
- **A releitura por região faz um [recorte](glossary.md#recorte) por valor que falhou.** Uma
  página com muitos valores inválidos custa muitas chamadas ao leitor caro.
  O recorte é justo, sem folga em volta. O que o leitor caro devolve é o
  que estava dentro da caixa das linhas que falharam.
- **O elemento fixo depende da repetição e só vê o que a execução leu.**
  Uma página só, ou um documento sem linha repetida no mesmo lugar, não tem
  elemento fixo. Um carimbo que só uma página tem, dentro do cabeçalho,
  deixa o resto do cabeçalho dessa página sem marca. O cabeçalho e o rodapé
  de um formulário pré-impresso contam como elementos fixos.
- **Numa página lida de lado, a
  [ordem por layout](concepts/cascade.md#ordem-de-leitura-por-layout) olha
  a página deitada.** Com `layout=`, os blocos, os rótulos e a ordem vêm da
  imagem, e não da leitura.
- **A repetição compara o lugar na imagem.** A mesma linha numa página em
  pé e numa página lida de lado não conta como repetida, e os
  [elementos fixos](concepts/cascade.md#os-elementos-fixos-da-pagina) não a
  veem.
- **A página lida de lado custa duas leituras.** Quando a maioria das
  linhas detectadas é mais alta que larga, o PP-OCR lê a página de novo,
  girada, e fica a leitura com mais linhas deitadas. A página em pé comum
  paga uma leitura só.
- **Uma página nato-digital paga o OCR de cada raster que nenhuma camada
  leu.** O leitor de pixels lê o recorte de cada um, com a folga
  `RASTER_MARGIN` em volta, e os recortes que se tocam viram um só. Ficam de
  fora os rasters menores que `process(min_raster_fraction=)`. A página sem
  raster não paga nada.
- **Um servidor `vlm` local sem `served=` é consultado uma vez.** Na
  primeira vez que a versão de saída é pedida, o leitor pergunta ao
  servidor qual modelo ele serve. Num servidor externo, `served=` é
  obrigatório.
- **O que a estrutura do PDF não vê.** Quando há texto no desenho, conta
  como lido o corpo em contornos de glifo feitos só de retas, e o trecho
  curto em contornos. O contrário também acontece: um gráfico de pizza ou
  um mapa sem texto por cima, com muitos caminhos curvos, vai aos pixels.
  Ver [Substrato](concepts/substrate.md#o-que-a-estrutura-nao-ve).
