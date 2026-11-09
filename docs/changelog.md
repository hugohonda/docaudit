# Versões e mudanças

## Como a versão é numerada

A versão sai da tag do git, e `docaudit.__version__` a devolve.

- Em desenvolvimento, as versões são `0.1.0.devN`, cada uma com a tag
  `v0.1.0.devN`. A primeira foi `0.1.0.dev0`.
- Depois, o pacote fica em `0.y.z` enquanto a API mudar. `y` sobe quando
  algo público quebra; `z` sobe quando nada quebra.

O pacote não vai ao PyPI enquanto não estiver maduro. Nenhuma tag dispara a
publicação: o workflow que publica roda só à mão.

## Como fixar uma versão

Uma tag `v*` publicada não muda, e a `main` não recebe push forçado nem é
apagada. As regras do repositório no GitHub recusam os dois, sem exceção.
Uma tag errada fica, e a próxima a corrige. Por isso o commit ou a tag que
você fixou continua lá.

Fixe pela tag:

```bash
uv add "docaudit[ppocr,openvino] @ git+https://github.com/hugohonda/docaudit@v0.1.0.dev1"
```

Ou pelo commit, que é o que o `uv.lock` grava de qualquer forma:

```bash
uv add "docaudit[ppocr,openvino] @ git+https://github.com/hugohonda/docaudit@<commit>"
```

## Mudanças

O registro segue o formato do [Keep a Changelog](https://keepachangelog.com/1.1.0/).

--8<-- "CHANGELOG.md:versoes"
