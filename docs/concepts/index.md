# Como a leitura funciona

Esta seção explica o que a biblioteca decide por você e por quê. Os
argumentos de cada função estão em [Configuração](../configuration.md), e
as tarefas passo a passo estão nos guias, como
[Escalar só o que falhou](../how-to/escalate.md).

## O caminho de uma página

`process()` abre o documento uma vez e leva cada página por seis etapas, do
substrato ao resultado. Cada seção abaixo resume uma etapa, na ordem, e
aponta a página que a explica.

## Substrato

Da estrutura do PDF, sem renderizar, sai o
[substrato](../glossary.md#substrato) da página: de onde veio a camada de
texto. Sai também o que nenhuma camada leu. Ver [Substrato](substrate.md).

## Cascata

A [etapa barata](../glossary.md#etapa-barata) lê a página com a
[cascata](../glossary.md#cascata), a lista de leitores baratos. Vale a
primeira leitura não vazia, e o leitor seguinte lê os rasters que a camada
de texto não leu. Ver [Cascata e elementos fixos](cascade.md).

## Política

A política decide que páginas [encaminhar](../glossary.md#encaminhar) ao
[leitor caro](../glossary.md#leitor-caro). A política `evidence` encaminha
só onde a leitura barata provou ter falhado, e um
[teto](../glossary.md#teto) opcional limita o leitor caro. Ver
[Política, conferência e escalada](policy.md).

## Releitura por outra família

Antes do leitor caro, outra [família](../glossary.md#familia) relê a página
encaminhada por uma verificação. Ela separa o erro impresso no documento do
erro de leitura. Ver
[Reler com outra família](policy.md#reler-com-outra-familia-antes-do-leitor-caro).

## Leitor caro

O leitor caro lê a página inteira ou só o
[recorte](../glossary.md#recorte) das linhas que falharam. A leitura dele
passa pelas mesmas verificações antes de substituir a barata. Ver
[A leitura cara passa pelas mesmas verificações](policy.md#a-leitura-cara-passa-pelas-mesmas-verificacoes).

## Resultado

Sobre as linhas finais, a biblioteca marca os elementos fixos, acha a
[tarja](../glossary.md#tarja) e a [folha](../glossary.md#folha), refaz a
ordem por layout quando pedido e extrai as entidades. Cada
[trecho](../glossary.md#trecho) sai com página, caixa, leitor e ordem. Ver
[Os elementos fixos da página](cascade.md#os-elementos-fixos-da-pagina),
[Origem e cache](provenance.md) e
[Formato da resposta](../response/index.md).

## Dados que saem da máquina

Um leitor que envia a página para fora da máquina é recusado sem
`allow_external=True`. Ver [Segurança dos dados](../security.md).
