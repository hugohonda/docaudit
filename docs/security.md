# Segurança dos dados

O `docaudit` roda na máquina de quem o chama. Nada sai dela sem uma
autorização escrita no código.

## O que sai da máquina

Por padrão, nada. A camada de texto, o Tesseract, o PP-OCR e o detector de
layout rodam localmente. O leitor `vlm` apontado para um servidor na própria
máquina também.

Duas coisas acessam a rede:

| o quê | quando | o que vai |
|---|---|---|
| download de pesos | na primeira leitura do PP-OCR e na primeira detecção de layout | só o pedido do arquivo de pesos; nenhum dado do documento |
| leitor `vlm` com host externo | a cada página ou região que ele lê | a imagem da página ou da região, e o prompt |

Os pesos do detector de layout são conferidos pelo SHA-256 depois de baixados.

## Como a biblioteca recusa um leitor externo

Todo leitor declara `external`. O leitor `vlm` calcula o valor pelo endereço:
é externo quando o host da URL não é `127.0.0.1`, `localhost` ou `::1`. Um
leitor de terceiros declara o próprio valor.

`process()` e `Document` recusam um leitor externo, na cascata barata, na
releitura ou no tier caro, com `ExternalBackendError`, antes de abrir o
documento. Usá-lo exige `allow_external=True` na chamada.

```python
from docaudit.backends.vlm import VLM

hosted = VLM("https://api.exemplo.com", "generic", served="modelo", api_key="...")
docaudit.process("documento.pdf", strong=hosted)  # ExternalBackendError
docaudit.process("documento.pdf", strong=hosted, allow_external=True)  # a página sai
```

A recusa olha a declaração do leitor, e não o conteúdo da página. A biblioteca
não procura dados pessoais no texto antes de enviá-lo. Anonimizar é passo de
quem usa a biblioteca.

## O que fica no disco

| o quê | onde | conteúdo |
|---|---|---|
| cache de leituras | `ModelCallCache(path)`, ou `<DOCAUDIT_CACHE_DIR>/calls.sqlite` | o texto lido de cada página, em claro, com as caixas, num SQLite |
| pesos dos modelos | `<DOCAUDIT_CACHE_DIR>/models` | os arquivos dos modelos |

O cache guarda o conteúdo dos documentos. Trate o arquivo com o mesmo cuidado
que os próprios documentos: mesmas permissões, mesmo backup, mesmo descarte.
Apagar o arquivo apaga as leituras; nada mais depende dele.

## Dados pessoais

Autos judiciais trazem nomes, CPF e outros dados pessoais. Tratá-los está
sujeito à Lei Geral de Proteção de Dados (Lei 13.709/2018), e a
responsabilidade pelo tratamento é de quem usa a biblioteca.
