# Segurança

## Como relatar

Use o [relato privado de vulnerabilidade](https://github.com/hugohonda/docaudit/security/advisories/new) do GitHub. Não abra issue pública.

Vale relatar o que afeta o pacote `docaudit` e os workflows deste repositório. Falha numa
dependência vai para quem a mantém, e aqui ela entra pela regra abaixo.

## Dependências

Nenhuma dependência, action ou hook entra com menos de 7 dias de publicada:

- `exclude-newer` no `pyproject.toml` vale para o `uv lock`;
- `cooldown` no `.github/dependabot.yml` vale para os PRs do Dependabot;
- actions e hooks ficam fixados por hash.

A atualização automática de segurança do Dependabot fica desligada, porque ela ignora essa
janela. Uma correção urgente entra à mão, por pacote, com o motivo e a data de retirada.

O uso seguro da biblioteca está em [`docs/security.md`](docs/security.md).
