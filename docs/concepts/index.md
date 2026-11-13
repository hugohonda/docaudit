# Como a leitura funciona

Esta seção explica o que a biblioteca decide por você e por quê. Os
argumentos de cada função estão em [Configuração](../configuration.md), e
as tarefas passo a passo estão nos guias, como
[Escalar só o que falhou](../how-to/escalate.md).

## O caminho de uma página

`process()` abre o documento uma vez e leva cada página por estas etapas:

1. **Substrato.** Da estrutura do PDF, sem renderizar, sai de onde veio a
   camada de texto e o que nenhuma camada leu.
2. **Cascata.** A [etapa barata](../glossary.md#etapa-barata) lê a página com a lista de leitores baratos.
   Vale a primeira leitura não vazia, e o leitor seguinte lê os rasters
   que a camada de texto não leu.
3. **Política.** A política decide que páginas [encaminhar](../glossary.md#encaminhar) ao
   [leitor caro](../glossary.md#leitor-caro).
   A política `evidence` encaminha só onde a leitura barata provou ter
   falhado.
4. **Releitura por outra família.** Antes do leitor caro, outra [família](../glossary.md#familia)
   relê a página encaminhada por uma verificação. Ela separa o erro
   impresso no documento do erro de leitura.
5. **Leitor caro.** O leitor caro lê a página inteira ou só o [recorte](../glossary.md#recorte) das
   linhas que falharam. A leitura dele passa pelas mesmas verificações
   antes de substituir a barata.
6. **Resultado.** Sobre as linhas finais, a biblioteca marca os elementos
   fixos, acha a [tarja](../glossary.md#tarja) e a [folha](../glossary.md#folha), refaz a ordem por layout quando pedido e
   extrai as entidades. Cada [trecho](../glossary.md#trecho) sai com página, caixa, leitor e ordem.

## Substrato

Cada página recebe um de três substratos: `BORN_DIGITAL`,
`SEARCHABLE_SCAN` ou `IMAGE_ONLY`. A classe sai do modo como o texto foi
desenhado e da ordem dos objetos no fluxo da página, sem limiar. Ela muda o
que uma verificação que falha quer dizer: erro de leitura numa
digitalização, erro do documento numa página nato-digital. `Page.unread`
lista os rasters e desenhos que nenhuma camada leu. Ver
[Substrato](substrate.md).

## Cascata

A cascata padrão é `["text_layer", "ppocr"]`: a camada de texto onde
houver, o PP-OCR no resto. OCR é o reconhecimento óptico de caracteres. Numa digitalização com [camada de OCR](../glossary.md#camada-de-ocr), os pixels
são a leitura, e a camada fica como outra família já paga. O leitor de
pixels lê só os rasters que a camada não leu, com uma folga em volta. As
linhas que se repetem no mesmo lugar em outras páginas são marcadas como
elementos fixos. Ver [Cascata e elementos fixos](cascade.md).

## Política

A política decide antes da leitura barata, pelo substrato, ou depois dela,
pelas leituras. `evidence` conta sinais categóricos: leitura vazia, texto
mal decodificado e valores que falham uma verificação, como o dígito
verificador de um CPF (Cadastro de Pessoas Físicas). Um [teto](../glossary.md#teto) opcional (`Budget`) limita as páginas e o
tempo do leitor caro. Ver [Política, conferência e escalada](policy.md).

## Releitura por outra família

Uma família é um motor de outra arquitetura e outro treino. Quando duas
famílias leem na página os mesmos valores inválidos, o erro está impresso
no documento, e a página não paga o leitor caro. Quando a releitura traz um
valor que confere no mesmo lugar, a linha troca. Ver
[Reler com outra família](policy.md#reler-com-outra-familia-antes-do-leitor-caro).

## Leitor caro

O leitor caro lê a página inteira ou, com `reread="region"`, um recorte
por valor que falhou. A leitura dele substitui a barata só onde leu. A
linha cara que perde um valor que a barata tinha certo é recusada. Ver
[A leitura cara passa pelas mesmas verificações](policy.md#a-leitura-cara-passa-pelas-mesmas-verificacoes).

## Resultado

Cada trecho guarda a página, a caixa normalizada, o leitor e um
identificador que depende só do conteúdo. A linha que saiu fica em
`Result.others`, ao lado da que entrou. `RoutingDecision.steps` conta o que
aconteceu com cada página. O cache guarda as leituras com uma chave que
muda quando a leitura pode mudar. Ver [Origem e cache](provenance.md) e
[Formato da resposta](../response/index.md).

## Dados que saem da máquina

Um leitor que envia a página para fora da máquina é recusado sem
`allow_external=True`. Ver [Segurança dos dados](../security.md).
