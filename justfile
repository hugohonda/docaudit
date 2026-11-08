# Uma receita por tarefa; a CI chama as mesmas. `just` lista tudo.
# O `just` vem do uv.lock (`rust-just`): `uv run just <receita>` sem instalar nada.

extras := "--extra tesseract --extra ppocr --extra vlm --extra layout --extra openvino --extra mojibake"

[private]
default:
    @just --list

# Ambiente completo, do lock, e os hooks do commit.
setup:
    uv sync --locked --all-groups {{extras}}
    uv run prek install

# Os hooks do commit em todos os arquivos: ruff, pyright, ty, lock, workflows.
lint:
    uv run prek run --all-files --show-diff-on-failure

# Corrige o que o ruff corrige sozinho.
fmt:
    uv run ruff check --fix .
    uv run ruff format .

# Testes rápidos, com o piso de cobertura do pyproject.
test *args:
    uv run pytest -m "not slow" --cov {{args}}

# Tudo, inclusive `real`, que baixa um PDF público.
test-all:
    uv run pytest

# A cascata com os motores de verdade; pede o binário do Tesseract.
integration:
    uv run pytest -m integration

docs:
    uv run mkdocs build --strict

serve:
    uv run mkdocs serve

build:
    uv build
    uv export --quiet -o pylock.toml

# O check obrigatório do PR (`ci.yml`).
ci: lint test docs build

# O que o `ci-completo` roda: as outras versões do Python e a integração.
full:
    for py in 3.12 3.13; do uv run -p $py --isolated --locked --all-groups {{extras}} pytest -m "not slow" -q; done
    just integration

upgrade pkg:
    uv lock --upgrade-package {{pkg}}
