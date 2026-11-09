# Comparação

Esta página é para quem conhece Docling, Marker, MinerU, olmOCR,
LlamaParse, Unstructured ou os serviços de nuvem (Textract, Document AI,
ADE). Ela mostra o que o `docaudit` faz igual, o que faz diferente e o que
não faz. As diferenças vêm de três escolhas:

- verificações que mostram onde a leitura está provadamente errada;
- a releitura por outra [família](glossary.md#familia), que separa o erro do documento do erro de
  leitura;
- a origem de cada linha.

Os termos do `docaudit`, como [leitor caro](glossary.md#leitor-caro), [teto](glossary.md#teto) e
[recorte](glossary.md#recorte), estão no [Glossário](glossary.md). Cada comportamento de
terceiro citado tem a fonte no fim da página.

## O que é igual

- **[Trecho](glossary.md#trecho) com página, caixa normalizada em `[0, 1]`, leitor de origem e
  confiança.** O ADE da Landing AI devolve caixas normalizadas da mesma
  forma [3]. O contrato de OCR (reconhecimento óptico de caracteres) do LiteParse usa a mesma origem, no canto
  superior esquerdo, em pixels [8].
- **Leitores por entry point, com permissão explícita para o que sai da
  máquina.** O Docling carrega plugins pelo grupo `docling` e recusa os de
  terceiros sem `allow_external_plugins` [2]. Aqui a permissão é
  `allow_external`, e ela protege o dado, e não o código: `external` vem do
  endereço do servidor.
- **Ler os pixels só onde a camada de texto não leu.** O Docling, nos modos
  `DEFAULT` e `PDF_AWARE_LAYOUT_REGIONS`, passa OCR em três tipos de região
  de layout [2]. São as que cobrem um bitmap, as que não têm texto
  programático e as que têm desenho que o texto não explica. O LiteParse passa OCR só nas imagens
  embutidas e nas páginas sem texto nativo [8].
- **Cache de leituras.** O LlamaParse guarda o resultado de um arquivo por
  48 horas [6]. Aqui a chave leva o hash do documento, a página, o DPI, o
  leitor e a versão do que ele devolve. Nenhum pixel entra nela.

## O que é diferente

| escolha | o que faz | o análogo mais próximo | a diferença |
|---|---|---|---|
| substrato pelo modo de desenho e pela ordem do fluxo | classifica a página em nato-digital, digitalizada com OCR e digitalizada sem OCR. Conta o texto desenhado sem tinta e o texto coberto por uma imagem desenhada depois | o OCRmyPDF, no modo `redo`, separa o texto visível do invisível e declara que não distingue o texto visível pintado por cima [7]; o Marker, com `strip_existing_ocr`, pula a página com texto em modo invisível [1] | a classe é usada adiante: uma verificação que falha só conta como leitura errada onde o texto veio de um motor. A regra do texto coberto por imagem cobre o caso que o OCRmyPDF declara não ver |
| rasters não lidos vão ao leitor seguinte | a imagem e o desenho sem texto dentro viram caixas que o leitor seguinte da cascata lê. Os recortes que se tocam viram um só, sem modelo de layout | Docling `PDF_AWARE_LAYOUT_REGIONS` [2] | decidir não roda modelo; o Docling roda um detector de layout por página. O glifo desenhado em contorno entra pela forma do caminho, preenchido e com curva, sem renderizar a página. O glifo feito só de retas é ponto cego declarado |
| evidência categórica de leitura errada | `Check`: forma impressa mais regra de validade (módulo 11, módulo 97, grafia do valor). `FailsCheck` conta as falhas, sem número ajustado | Marker `detect_bad_ocr`, com razões de espaço, quebra de linha e alfanuméricos de 0,7, 0,6 e 0,3 [1]; ADE `low_confidence_spans`, com corte em 0,95 [3]; AdaParse escolhe o leitor de cada documento com um modelo treinado por preferência humana [4] | o campo se confere sozinho, e os falsos positivos têm nome, como o erro do próprio documento. Você acrescenta os seus campos, inclusive com as funções `is_valid` do python-stdnum |
| reler a página com o leitor caro quando um gatilho dispara | a página vai ao leitor caro só quando uma verificação falhou e a releitura por outra família não explicou a falha | o modo automático do LlamaParse relê a página num modo mais caro quando ela tem tabela, imagem, um texto ou uma expressão regular, sem teto [9] | o gatilho do LlamaParse diz o que a página contém; o daqui mostra que a leitura está errada. O teto em páginas e em tempo é opcional |
| releitura por outra família (`confirm=`) | o mesmo valor inválido em dois leitores de famílias diferentes fica como erro do documento. Um valor que confere no mesmo lugar troca a linha. Só o resto vai ao leitor caro | os sistemas citados nesta página não têm passo equivalente | o erro impresso no papel não gasta o leitor caro e fica nomeado no resultado |
| troca só do que o leitor caro leu | a leitura cara substitui a barata só dentro das caixas que ela devolveu | o olmOCR cai para o `pdftotext` depois de esgotar as tentativas do modelo numa página [5] | a linha barata que o leitor caro descartou, como a tarja da margem, fica no resultado |
| DPI por página, do raster nativo | cada página é renderizada na resolução do maior raster dela, presa a um intervalo, e o DPI entra na chave do cache | o olmOCR renderiza com 1288 pixels no lado maior [5] | o DPI na chave do cache evita servir uma leitura de outra resolução |
| um `Protocol` `Reader` para as duas etapas | o leitor barato e o leitor caro implementam o mesmo `Protocol`; `output_version` entra na chave do cache | o LiteParse publica um contrato HTTP para um servidor de OCR externo [8] | o que muda entre as etapas é quem decide chamar, e não a interface |
| gasto sem o que o cache serviu | `Result.spent` desconta o que o cache serviu, do lado de quem chama | o ADE devolve `credit_usage` do lado do servidor [3] | uma execução servida pelo cache não relata o gasto de uma que chamou o leitor |

## O formato da resposta ao lado de outras ferramentas

A forma da resposta é a mesma das ferramentas de análise de documentos
atuais, com outros nomes. Há uma lista de blocos com página e caixa
normalizada e um identificador por bloco. Há o texto em Markdown, ligado
aos blocos pelo identificador.

| o que | docaudit | Landing AI ADE | Docling | Reducto | Mistral OCR |
|---|---|---|---|---|---|
| bloco com texto | `Chunk`, uma linha ou uma região | `chunks[]` | `texts[]`, `tables[]` | `blocks[]` dentro de `chunks[]` | `pages[].markdown` |
| página e caixa | `page`, `bbox` em `[0, 1]`, origem no alto à esquerda | `grounding.page`, `grounding.box` em `[0, 1]` | `prov.page_no`, `prov.bbox` | `bbox` em `[0, 1]`, com `page` | caixa por imagem e, no OCR 4, por bloco |
| identificador | `Chunk.id`, do conteúdo e da posição | `id`, um UUID | `self_ref`, um ponteiro JSON | não há um estável | `id` da imagem |
| tipo do bloco | `kind`, quando há detector de layout | `type`: text, table, figure, logo... | `label` | `type` | rótulo do bloco, no OCR 4 |
| Markdown ligado ao bloco | `[p3:12]` em `to_markdown(annotated=True)` | âncora `<a id=...>` antes de cada bloco | exportação, sem âncora | `content` em cada item de `chunks[]` | não |
| confiança | `confidence`, crua, do motor | `confidence` e `low_confidence_spans` | não | `high`/`low`, ou número | por página ou palavra, no OCR 4 |
| cabeçalho e rodapé | `furniture`, sem apagar | `marginalia` | árvore `furniture` | tipo `Header`/`Footer` | campos de cabeçalho e rodapé, no OCR 4 |
| figura | `figures()`, com as linhas lidas nela | item `figure` em `chunks[]` | `pictures[]` | bloco `Figure` | `images[]`, com a imagem em base64 |
| quem leu cada bloco | `source` | não | não | não | não |
| se o valor confere | `Entity.state` | não | não | não | não |
| por que a página foi relida | `RoutingDecision.reason` e `steps` | não | não | não | não |
| o que custou | `Spent`, por etapa, sem o que o cache serviu | `credit_usage` | não | uso na conta | uso na conta |

As quatro últimas linhas são o que a biblioteca acrescenta. As faltas estão
em [Limites](limits.md): célula de tabela, confiança por palavra e
hierarquia de seções. A forma da resposta do `docaudit` está em
[Formato da resposta](response/index.md).

Os nomes de campo de terceiros vêm das documentações deles e mudam entre
versões. As fontes são a Landing AI na
[resposta do ADE](https://docs.landing.ai/ade/ade-json-response), o Docling
no [modelo do documento](https://docling-project.github.io/docling/concepts/docling_document/),
a Reducto no [formato da resposta](https://docs.reducto.ai/parse/response-format).

## O que o docaudit não faz

Tabela em células, extração por esquema, confiança por palavra, detecção de
página de cabeça para baixo e API assíncrona, entre outros. A lista e os
comportamentos conhecidos estão em [Limites](limits.md). A ordem de custo
que sustenta as escolhas está em [Desempenho](performance.md).

## Fontes

Conferidas em outubro de 2026. O comportamento de um projeto de terceiros
muda entre versões.

1. Marker, `marker/providers/pdf.py`: `detect_bad_ocr`, `strip_existing_ocr`.
   <https://github.com/datalab-to/marker/blob/master/marker/providers/pdf.py>
2. Docling, `docling/models/base_ocr_model.py` (modos de OCR e junção de
   células) e a página de plugins.
   <https://github.com/docling-project/docling/blob/main/docling/models/base_ocr_model.py>,
   <https://docling-project.github.io/docling/concepts/plugins/>
3. Landing AI, ADE: confiança e `low_confidence_spans`; início rápido, com
   `credit_usage`; caixas normalizadas.
   <https://landing.ai/blog/introducing-confidence-scores-surface-parsing-uncertainty-before-it-becomes-a-problem>,
   <https://docs.landing.ai/ade/ade-quickstart>,
   <https://landing.ai/developers/the-ade-storybook-part-3>
4. Siebenschuh et al., *AdaParse*, MLSys 2025. <https://arxiv.org/abs/2505.01435>
5. olmOCR, `olmocr/pipeline.py` (`--target_longest_image_dim`,
   `--max_page_retries`, `make_fallback_result`), e o artigo.
   <https://github.com/allenai/olmocr/blob/main/olmocr/pipeline.py>,
   <https://arxiv.org/abs/2502.18443>
6. LlamaParse, opções de cache.
   <https://developers.llamaindex.ai/llamaparse/parse/v1/features/cache_options/>
7. OCRmyPDF, recursos avançados: modos de texto existente.
   <https://ocrmypdf.readthedocs.io/en/stable/advanced.html>
8. LiteParse, configuração de OCR e contrato do servidor.
   <https://developers.llamaindex.ai/liteparse/guides/ocr>
9. LlamaParse, modo automático.
   <https://docs.cloud.llamaindex.ai/llamaparse/parsing/auto_mode>
