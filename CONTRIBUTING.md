# Contribuindo

## Ambiente

Só o [uv](https://docs.astral.sh/uv/) é obrigatório. Ele resolve o Python e as
dependências; não há passo de `activate`.

```bash
git clone git@github.com:hugohonda/docaudit.git
cd docaudit
uv run just setup     # o ambiente do lock e os hooks do commit
```

O `just` vem do `uv.lock`, como ruff, pyright, ty, pytest, prek e o mkdocs:
nada a instalar além do uv. `just` sem argumento lista as receitas.

O extra `tesseract` precisa do binário no sistema:

```bash
brew install tesseract tesseract-lang                 # macOS
sudo apt-get install tesseract-ocr tesseract-ocr-por  # Debian ou Ubuntu
```

## Antes de abrir um PR

```bash
uv run just ci             # o mesmo que o check obrigatório da CI
```

O rótulo `ci:completo` no PR acrescenta as outras versões do Python, o macOS e
a integração com o Tesseract (`just full` no laptop): ponha-o no PR que mexe em
dependência, leitura de PDF, leitor ou versão do Python. Fora da CI ficam os
testes `real`, que baixam um PDF da rede; vale rodá-los antes de mexer em
leitura ou em substrato:

```bash
uv run just test-all
```

Os testes marcados com `real` baixam um PDF público na primeira execução e o
guardam em `tests/real/.pdfs`. Sem rede, eles pulam. Para reaproveitar um cache
entre clones, aponte `DOCAUDIT_TEST_CACHE` para um diretório seu:

```bash
export DOCAUDIT_TEST_CACHE=~/.cache/docaudit-tests
```

## Escrevendo um leitor

Ver [docs/writing-a-reader.md](docs/writing-a-reader.md). Um leitor novo herda
`ReaderContract` de `tests/support` e fornece a fixture `reader`.

## Convenções

As convenções de código, idioma e prosa estão em [AGENTS.md](AGENTS.md) e valem
igualmente para contribuições humanas. As duas que mais surpreendem quem chega:

- Identificadores em inglês, docstrings e comentários em português.
- Um campo que nada produz não entra. Tipo, campo, membro de enum e parâmetro
  entram no commit que os preenche e os lê, não antes.

## Documentação

```bash
uv run just serve
```

Sobe em <http://127.0.0.1:8000> com recarga automática. A referência de API é
gerada das docstrings. `mkdocs build --strict` roda na CI, então uma referência
quebrada falha o build em vez de produzir página com buraco.

## Versionamento

A versão sai da tag do git. A primeira versão é `0.1.0.dev0`, com a tag `v0.1.0.dev0`.
Enquanto o pacote estiver em desenvolvimento, as versões seguem em `0.1.0.devN`. Depois, o
pacote fica em `0.y.z` enquanto a API mudar: `y` sobe quando algo público quebra, `z` quando não.

O pacote não vai ao PyPI enquanto não estiver maduro: o workflow `publish`
roda só à mão, e nenhuma tag o dispara. Quem usa a biblioteca a instala pelo
git, fixada num commit.

Uma tag `v*` publicada é imutável, e a `main` não recebe push forçado nem é
apagada: as regras do repositório no GitHub recusam os dois, sem exceção para
ninguém. Uma tag errada fica, e a próxima a corrige. Quem fixa um commit ou
uma tag pode confiar que o que fixou continua lá.
