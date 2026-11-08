# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/1.1.0/).
Versionamento: [SemVer](https://semver.org/lang/pt-BR/): o maior sobe quando
algo público quebra, o menor quando algo entra, o último numa correção.
Antes da 1.0.0, a API pode mudar numa versão menor.

## [Não lançado]

### Adicionado

- `Result.records()`: as linhas de cada página em fileiras e blocos, só pela posição das
  caixas, com `Record.text` e `Record.tabular`. `Result.pieces()`: as páginas seguidas com a
  mesma tarja, por `Stamp.code`.
- `Budget.max_seconds`: o teto de tempo a partir do qual o leitor caro não começa página nova.
- `process(min_raster_fraction=)`: o piso de área abaixo do qual um raster de uma página
  nato-digital não vai ao leitor de pixels. Padrão `0.0`, o comportamento de antes; o valor não
  está calibrado.
- `PPOCR(det=)`: um detector ONNX próprio, com o hash no nome e na versão de saída.
- `VLM(retries=)`: repete a chamada que o servidor recusou por carga, que esgotou o tempo ou
  cuja conexão caiu. Num servidor fora da máquina, a recusa esgotada é falha da página, e o
  documento segue.
- `StampFormat.tz`: o fuso do tribunal, que torna `Stamp.at` ciente do fuso. Sem ele, a hora
  fica como impressa.
- Um leitor `vlm` com o mesmo detector de `process(layout=)` reaproveita os blocos já detectados
  da página, em vez de detectar de novo.

### Alterado

- A licença passa de Apache-2.0 para MPL-2.0. Cada arquivo fonte traz o aviso do Anexo A.
- O leitor caro não prova mais erro do documento: `Entity.printed` sai só da camada de
  texto ou da releitura por outra família (#7).
- `docaudit` exporta `Run`, `Region` e `Layout`, que já eram parte de `Result` e de
  `process(layout=)`.
- O classificador do pacote passa de Pre-Alpha para Alpha, como o README diz.

### Corrigido

- `pixels_of` destrói o bitmap do pdfium sob o lock e devolve, em cinza, uma cópia que não
  aponta para o buffer dele.
- Em ARM64, o OpenCV fica abaixo de 4.14: o `resize` das versões 4.14 e 5.0 lê além da
  imagem e derruba o processo (#8).
- O workflow de documentação instala o pacote, que o mkdocstrings importa, e o de
  publicação só segue a partir de uma tag `v*`.

## [0.1.0.dev0] - 2026-11-05

A primeira versão, em desenvolvimento. O pacote lê documentos digitalizados em português do
Brasil, confere a leitura com regras que o documento permite checar e devolve cada trecho
com a página, a caixa e o leitor de origem.

- Leitores: camada de texto, Tesseract, PP-OCR (ONNX Runtime ou OpenVINO) e um servidor
  compatível com a API da OpenAI (`vlm`); detector de layout `PPDocLayout`.
- Políticas `all_cheap`, `all_strong` e `evidence`; releitura por outra família com
  `confirm=`; teto de páginas em `Budget`.
- Doze entidades padrão com estado `confirmed`, `well_formed` ou `failed`, e `Check` para
  campos próprios.
- `Result.to_markdown(annotated=True)` e `Result.cited` para um agente; `Document` e
  `Doubt` para uma sessão; `visualize` para a imagem com as caixas.
- Cache de leituras em SQLite; nada sai da máquina sem `allow_external=True`.

[Não lançado]: https://github.com/hugohonda/docaudit/compare/v0.1.0.dev0...HEAD
[0.1.0.dev0]: https://github.com/hugohonda/docaudit/releases/tag/v0.1.0.dev0
