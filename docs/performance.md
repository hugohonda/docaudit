# Desempenho

Esta página dá a ordem de custo de cada etapa e os padrões que vêm dela.
Os números dependem da máquina, dos leitores e do documento. Meça nos seus
documentos com `RoutingDecision.seconds` e `Result.spent` antes de estimar
um custo.

## Custo por etapa

Numa página, do mais barato ao mais caro:

1. **Decidir o substrato.** Lê só a lista de objetos do PDF, sem desenhar
   nada.
2. **Tirar as linhas da camada de texto.** Une as caixas dos glifos em
   linhas, o que custa mais que os retângulos crus do pdfium.
3. **Renderizar a página.** Desenha a página inteira em pixels. Em RGB
   custa mais que em tons de cinza.
4. **Ler os pixels com OCR (reconhecimento óptico de caracteres).** Roda redes neurais sobre a imagem, linha a
   linha.

Decidir o substrato custa uma pequena fração da renderização que ele evita.
A camada de texto lê uma página nato-digital sem renderizar. Por isso a
cascata padrão começa pela camada, e o OCR lê só o que ela não leu.

## Renderização, cor e lock

**Uma renderização por página que pode escalar.** A leitura barata, a
releitura por outra [família](glossary.md#familia) e a leitura cara usam a mesma renderização. Ela
fica guardada só na página que tem por onde [escalar](glossary.md#escalar): leitura vazia, ou
valores que falham até o mínimo da política. As outras páginas soltam a
renderização ao sair da [etapa barata](glossary.md#etapa-barata). A página [encaminhada](glossary.md#encaminhar) por outro sinal
é renderizada de novo.

**Um modo de cor por leitor.** O Tesseract pede tons de cinza, porque
converte para cinza de qualquer forma. O PP-OCR e o modelo de visão e
linguagem pedem RGB, o formato em que os pesos deles foram treinados. Cada
modo é guardado à parte. Um leitor que pede outro modo paga a renderização
dele.

**TIFF no caminho do Tesseract.** O `pytesseract` grava um arquivo
temporário no formato que a imagem declara. A imagem vai rotulada como TIFF,
que é sem perda, e o PNG não é comprimido de novo.

**Lock em vez de vários processos.** O pdfium não é seguro para uso
concorrente, e todo acesso a ele passa por um lock. O OCR, que domina o
tempo de uma página, roda fora do lock. Serializar só o pdfium custa menos
que passar páginas entre processos do sistema operacional.

## Leitores

Por página, do mais barato ao mais caro:

| leitor | o que custa |
|---|---|
| `text_layer` | só a extração das linhas; não renderiza |
| `TesseractOCR()` | o mais barato dos leitores de pixels |
| `PPOCR()`, `v5-latin`, o padrão | detecção e reconhecimento leves, em ONNX |
| `PPOCR(models="v6-medium")` | os mesmos passos, com redes maiores |
| `VLM()` | um modelo de visão e linguagem por região ou pela página, num servidor |

O PP-OCR `v5-latin` é o padrão da cascata. Ele lê páginas digitalizadas
melhor que o Tesseract, a um custo maior.

O motor do PP-OCR sai do extra instalado. Com `engine="auto"`, o padrão, ele
usa o OpenVINO quando o extra `openvino` está instalado, e o ONNX Runtime
quando não está. Os dois leem os mesmos arquivos de pesos, e na CPU o
OpenVINO é o mais rápido. O motor entra em `output_version`, e as leituras
de um não servem pelo outro no cache.

O `v6-medium` custa várias vezes o padrão por página. Em página impressa
ele erra um pouco menos. Em foto e em manuscrito, não erra menos. Numa
cascata, o que ele compra é o conserto das linhas que falharam uma
verificação, e não uma leitura melhor da página inteira. Ele é da mesma
família do padrão e erra junto com ele em parte dos casos. Nenhum leitor
caro prova erro do documento: só a releitura por `confirm=`, de outra
família, e a camada de OCR provam.

`strong=` não tem padrão, porque o [leitor caro](glossary.md#leitor-caro) certo depende do documento e
do [teto](glossary.md#teto). A densidade da página não é sinal para encaminhar. Um modelo de visão
e linguagem custa mais, e na página inteira pode perder valores em página densa.
Compare os leitores nos seus documentos. Para ligar um modelo de visão e
linguagem por região, ver
[Ligar um modelo de visão e linguagem](how-to/vlm.md).

O detector de layout custa uma detecção por página, na mesma renderização
da leitura. O tempo dela entra na etapa em que a página foi renderizada.

## DPI por página

Uma página com raster é renderizada na resolução nativa do maior raster
dela, presa ao intervalo de `MIN_NATIVE_DPI` a `MAX_NATIVE_DPI`. Renderizar
acima da resolução do raster não cria pixels que a digitalização não tem,
e custa mais. Renderizar abaixo perde o que a digitalização tem. Uma página
sem raster é renderizada em `DEFAULT_DPI`.

O teto existe porque renderizar todas as páginas na resolução mais alta
custou mais e não leu melhor. O piso não tem medição que o separe de outro
valor. `process(dpi=)` fixa um DPI para todas as páginas.

## Seleção de páginas

`process(pages=)` restringe o processamento a esses índices. As páginas de
fora nem chegam a ser carregadas. A classificação custa por página
carregada, e não por página do documento.

## Tempo por página

`RoutingDecision.seconds` traz, por página, os segundos de cada etapa que a
tocou: `cheap`, `confirm` e `strong`. Uma página que custa muito mais que
as vizinhas na etapa barata aponta para o reconhecedor. A mesma diferença
em `strong` aponta para o leitor caro ou para a rede.

## Memória, paralelismo e implantação

A memória do Python não cresce com o número de páginas: a renderização de
cada página sai assim que ela deixa de servir. `workers` distribui as
páginas da etapa barata em threads. O ganho vem do OCR que roda fora do
lock do pdfium, e a saída é a mesma em qualquer número de workers. O
PP-OCR roda uma inferência por vez em cada processo do sistema operacional, e já usa os núcleos
dentro dela. Na etapa cara, `workers` vale só para um leitor externo, que
espera a rede.

As regras de memória nativa, threads, processos, GPU e contêiner estão em
[Implantar num serviço](how-to/deploy.md).
