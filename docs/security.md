# Segurança dos dados

O `docaudit` roda na máquina de quem o chama. Nada sai dela sem uma
autorização escrita no código.

## O que sai da máquina

Por padrão, nada. A camada de texto, o Tesseract, o PP-OCR, um motor de OCR (reconhecimento óptico de caracteres), e o detector de
layout rodam na própria máquina. O leitor `vlm` apontado para um servidor
na própria máquina também.

Duas coisas acessam a rede:

| o quê | quando | o que vai |
|---|---|---|
| download de pesos | na primeira leitura do PP-OCR, ou em `PPOCR.prepare()`, e na primeira detecção de layout | só o pedido do arquivo de pesos; nenhum dado do documento |
| leitor `vlm` com servidor externo | a cada página ou região que ele lê | a imagem da página ou da região, e o prompt |

Os pesos do detector de layout são conferidos pelo SHA-256 depois de
baixados.

## Como a biblioteca recusa um leitor externo

Todo leitor declara `external`: se é [externo](glossary.md#externo), isto é, se envia a página para fora da máquina. O leitor `vlm` calcula o valor pelo
endereço: ele é externo quando o host da URL não é `127.0.0.1`, `localhost`
ou `::1`. Um leitor de terceiros declara o próprio valor.

`process()` e `Document` recusam um leitor externo com
`ExternalBackendError`, antes de abrir o documento. Vale para a cascata
barata, para `confirm=` e para o [leitor caro](glossary.md#leitor-caro). Usar um leitor externo exige
`allow_external=True` na chamada.

```python
import docaudit
from docaudit.backends.vlm import VLM

hosted = VLM("https://api.exemplo.com", "generic", served="modelo", api_key="...")
docaudit.process("documento.pdf", strong=hosted)  # ExternalBackendError
docaudit.process("documento.pdf", strong=hosted, allow_external=True)  # a página sai
```

!!! warning "`allow_external=True` envia a página para fora da máquina"
    A recusa olha a declaração do leitor, e não o conteúdo da página. A
    biblioteca não procura dados pessoais no texto antes de enviá-lo.
    Anonimizar fica com quem usa a biblioteca.

## O que fica no disco

| o quê | onde | conteúdo |
|---|---|---|
| cache de leituras | `ModelCallCache(path)`, ou `<DOCAUDIT_CACHE_DIR>/calls.sqlite` | o texto lido de cada página, em claro, com as caixas, num SQLite |
| pesos dos modelos | `<DOCAUDIT_CACHE_DIR>/models` | os arquivos dos modelos |

Sem `DOCAUDIT_CACHE_DIR`, a pasta é `~/.cache/docaudit`.

O cache guarda o conteúdo dos documentos e não expira: uma leitura fica até
o arquivo ser apagado. Trate o arquivo com o mesmo cuidado que os próprios
documentos: mesmas permissões, mesma cópia de segurança, mesmo descarte.

Não há como apagar um documento só. Apagar o arquivo apaga as leituras, e
nada mais depende dele. Para ter um prazo de retenção por lote, dê a cada
lote o seu arquivo de cache.

## Dados pessoais

Os [autos](glossary.md#autos) de um processo judicial trazem nomes, CPF (Cadastro de Pessoas
Físicas) e outros dados pessoais. O tratamento deles está sujeito à Lei
Geral de Proteção de Dados (Lei 13.709/2018), e a responsabilidade é de quem
usa a biblioteca.

O que a biblioteca dá para isso é a lista de entidades com a caixa de cada
uma. A receita [Redigir dados pessoais](recipes/redact.md) cobre na imagem
e tira do texto cada identificador com dígito verificador que a leitura
achou.
