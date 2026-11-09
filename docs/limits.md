# Limites

O que o `docaudit` não faz, e os comportamentos conhecidos que quem o usa
precisa saber antes de confiar num resultado.

## O que não faz

- **Tabela como células.** A tabela sai como linhas, com as células separadas
  por ` | ` quando o leitor `vlm` a leu, e sem separador quando a leitura foi
  do tier barato. `Result.records()` junta em fileiras as linhas lado a lado
  e em blocos as fileiras vizinhas, só pela posição das caixas; não há
  coluna, cabeçalho nem célula mesclada. Montar a tabela a partir disso é
  passo de quem usa a biblioteca.
- **Extração de campos por esquema.** A biblioteca devolve texto com
  proveniência. Ela não preenche um esquema de campos, e não liga um valor
  extraído à caixa de onde ele veio além da caixa do trecho.
- **Confiança por palavra.** O trecho é a linha, ou a região, e a confiança é
  a média dela.
- **Carimbos lidos pelo leitor por região.** O detector de layout descarta,
  por padrão, as regiões rotuladas como carimbo, cabeçalho, rodapé, nota e
  texto lateral. O leitor `vlm` não as lê. As linhas delas ficam da leitura
  barata, quando o OCR barato as leu.
- **Rotação do conteúdo.** O `/Rotate` do arquivo é aplicado, e o PP-OCR
  lê em pé a página digitalizada de lado (`Chunk.turn`). O leitor de `strong`
  vê em pé a página que a leitura barata leu de lado. Na cascata barata, em
  `confirm` e em `Document.reread`, os outros leitores veem a imagem como ela é.
  Uma página escaneada de cabeça para baixo não é detectada.
- **Consistência entre páginas.** Os sinais veem uma página por vez. Conferir
  que o número do processo é o mesmo em todas as folhas exige olhar o
  documento inteiro, e não há gancho para isso além de uma política própria.
- **Que peça é cada peça.** `Result.pieces()` agrupa as páginas seguidas com a
  mesma tarja; dizer se a peça é petição, decisão ou certidão é de quem lê.
- **Exportação além de JSON e markdown simples.** Não há DocTags, HTML de
  documento nem formato de layout.
- **Idioma por página.** O idioma do OCR é um só por chamada.
- **API assíncrona.** `process()` é síncrono. Num servidor assíncrono, rode-o
  numa thread ou num processo à parte.

## Comportamentos conhecidos

- **O valor que perde a forma não é verificado.** Uma verificação só olha o
  texto que casa com a forma impressa do campo. Um CNPJ que o leitor
  devolveu sem a barra, um `R$` lido como `R5`, um número de processo que
  sumiu de uma tarja inclinada: nenhum casa, nenhum vira entidade, nenhum
  sinal dispara, e a página não é encaminhada por eles. A página sem valor
  `failed` não é página conferida. Quem precisa de um campo em toda folha
  confere a presença dele por conta própria, com `Result.entities` e
  `Page.stamp`.
- **Um valor errado pode fechar o dígito.** O dígito verificador prova que o
  valor é possível, não que é o impresso. No CPF e no CNPJ, que escrevem o
  resto 10 como 0, uma troca de um só dígito fecha de vez em quando; no
  número de processo, em módulo 97, nenhuma fecha, mas duas trocas podem.
  O estado `confirmed` é evidência forte, e não prova.
- **Um servidor `vlm` local que não responde à conexão interrompe o
  documento.** O servidor não está lá, e repetir não o traz. Num servidor
  fora da máquina a mesma recusa, o tempo esgotado e o 429 ou 5xx são falha
  da página, repetida `retries` vezes antes. Com `cache`, a segunda execução
  retoma do que já foi lido.
- **Uma resposta cortada no teto de tokens falha a página.** É o caso de um
  modelo que entra em laço de repetição. A página fica com a leitura barata.
- **O leitor `vlm` sem detector devolve a página como um trecho só.** A
  caixa cobre a folha, a página tem uma referência só em `Result.refs()`, e
  `Document.crop` dessa caixa é a página inteira. A linha, com a sua caixa,
  vem com `reread="region"` ou com `layout=`.
- **A escalada por região faz um recorte por valor que falhou.** Uma página
  com muitos valores inválidos custa muitas chamadas ao leitor caro. O
  recorte é justo, sem contexto em volta: o que o leitor caro devolve é o
  que estava dentro da caixa das linhas que falharam.
- **O elemento fixo da página é por repetição, e só vê o que a execução leu.** Uma página só,
  ou um documento sem linha repetida no mesmo lugar, não tem elemento fixo. Um
  carimbo de uma página só dentro do cabeçalho deixa o resto do cabeçalho
  dessa página sem marca. O cabeçalho e o rodapé de um formulário
  pré-impresso contam como elementos fixos.
- **Numa página lida de lado, a
  [ordem por layout](concepts.md#ordem-de-leitura-por-layout) olha a página
  deitada.** Com `layout=`, os blocos, os rótulos e a ordem vêm da imagem, e não
  da leitura.
- **A repetição compara o lugar na imagem.** A mesma linha numa página em pé e
  numa lida de lado não conta como repetida, e os
  [elementos fixos](concepts.md#os-elementos-fixos-da-pagina) não a veem.
- **A página lida de lado custa duas leituras.** Quando a maioria das linhas
  detectadas é alta, o PP-OCR lê a página de novo girada, e fica a leitura com
  mais linhas deitadas. A página em pé comum paga uma leitura só.
- **Uma página composta paga o OCR de cada raster que nenhuma camada leu.** O
  leitor de pixels lê o recorte de cada um, com a folga `RASTER_MARGIN` em
  volta; rasters que se tocam viram um recorte só. A página sem raster não
  paga nada.
- **Um servidor `vlm` local sem `served=` é consultado uma vez.** Na primeira
  vez que a versão de saída é pedida, o leitor pergunta ao servidor qual
  modelo ele serve. Num servidor fora da máquina, `served=` é obrigatório.
- **O que a estrutura do PDF não vê.** Quando há texto no desenho, conta
  como lido o corpo em contornos de glifo feitos só de retas, e o trecho
  curto em contornos, com poucos caminhos. O contrário também acontece: um
  gráfico de pizza ou um mapa sem texto por cima, com muitos caminhos
  curvos, vai aos pixels. Ver
  [Conceitos](concepts.md#o-que-a-estrutura-nao-ve).
