# docaudit

Guia para agentes de código que trabalham neste repositório.

`docaudit` lê documentos digitalizados em português do Brasil, confere a
própria leitura com regras que o documento permite checar, e devolve cada
trecho com a página, a caixa e o leitor de origem. O caso principal são os
autos judiciais. Classifica o substrato de cada página, lê tudo com uma
cascata de leitores baratos, aponta com verificações por regra onde a
leitura está provadamente errada, relê essas linhas com outra família de OCR
ou com um leitor caro. Não extrai campos, não decide por modelo e não
segmenta o auto em peças: isso é de quem a chama.

## Estrutura

```text
src/docaudit/
  types.py        dados e contratos (Protocols)
  pdf.py          pypdfium2: substrato, caixas de texto, renderização, PageView
  process.py      process(), a cascata barata e a leitura cara
  policies.py     as políticas de triagem
  registry.py     resolução de backend por entry point
  session.py      Document e Doubt: a superfície para um agente
  visualize.py    a imagem da página com a caixa de cada linha na cor do leitor
  cache.py        ModelCallCache
  backends/       textlayer, tesseract, ppocr, vlm, layout
tests/
  unit/ contracts/ integration/ real/
  support/        suíte de contrato e construtores de PDF (não distribuída)
docs/             MkDocs; a referência sai das docstrings
```

## Comandos

```bash
uv run just setup   # ambiente do lock e os hooks do commit
uv run just ci      # o check obrigatório do PR: hooks, testes, docs, pacote
uv run just full    # o ci-completo: Python 3.12 e 3.13 e a integração
uv run just fmt     # ruff --fix e format
```

O `just` vem do `uv.lock`; com ele no PATH, `just ci` basta. Os hooks
(`.pre-commit-config.yaml`, pelo prek) são ruff, pyright, ty, o lock, os
workflows e a higiene dos arquivos.

A CI chama as mesmas receitas. Em PR, um job só, `ci-ok`, roda `just ci`. O
`ci-completo` roda `just test` em 3.12, 3.13 e macOS e `just integration`,
com o rótulo `ci:completo` no PR, por acionamento manual e toda segunda;
peça-o no PR que mexe em dependência, leitura de PDF, leitor ou versão do
Python. O push na main não roda CI.

## Idioma

- **Identificadores em inglês**, sem exceção: nomes de função, variável, classe,
  arquivo e teste.
- **Docstrings e comentários em português do Brasil.**
- Não invente verbos a partir do inglês. Escreva "guarda o que já entregou", não
  "memoiza"; "entra no hash", não "hashear"; "documento aberto", não "handle".

## Prosa

- Escreva para quem nunca viu esta conversa. Não cite o histórico de iteração,
  nem decisões anteriores, nem o que o código já foi.
- Explique o comportamento atual e a razão dele. Evite "antes era", "a versão
  anterior", "isto substitui".
- Frases curtas. Acima de trinta palavras, quebre.
- Nada de travessão como aposto no meio da frase. Use vírgula, dois-pontos ou
  ponto.
- Não argumente com um crítico imaginário ("não é cerimônia", "não é detalhe").
- Número medido não vai para docstring nem para `docs/`, que fica com o custo e o
  porquê dos padrões. Na docstring fica a regra; o número envelhece e ninguém o revisa.
- Esta biblioteca não cita a dissertação que a originou. Quem a instala do PyPI
  não sabe o que é "documento 2, §4". A substância fica, a citação sai.

## O que entra no código

- **Um campo que nada produz não entra.** Não declare tipo, campo, membro de
  enum ou parâmetro antes de existir código que o preencha e código que o leia.
  Uma API que ninguém implementa é uma promessa que ninguém cumpre.
- **Um limiar precisa de medição ou de ausência.** Se não há como calibrar, ou o
  sinal é categórico, ou o número é parâmetro nomeado e documentado como
  não calibrado.
- **Uma garantia precisa ser verdadeira no caso principal.** Uma verificação que
  falha onde mais importa é pior que nenhuma, porque convida a confiar.
- Prefira deletar a abstrair. O risco declarado do projeto é excesso de
  engenharia de plataforma.

## Convenções de código

- `from __future__ import annotations` em todo módulo.
- Modelos de dados são `BaseModel` do Pydantic com `frozen=True`.
- Contratos de extensão são `typing.Protocol` com `@runtime_checkable`, não
  classes-base.
- Caixas são normalizadas a `[0, 1]` com origem no canto superior esquerdo.
  Pixels só aparecem na borda, em `to_pixels` e `from_pixels`.
- Imports pesados (pytesseract, PIL) ficam dentro do método que os usa, para que
  `import docaudit` custe só o núcleo.
- Todo acesso ao pdfium passa pelo lock de `docaudit.pdf`: a biblioteca não é
  segura para uso concorrente.
- `pyright` roda em modo `strict` sobre `src/` e no modo padrão sobre os testes;
  `ty` roda sobre `src/`. Os dois bloqueiam na CI
  e no pre-commit. Um `# pyright: ignore` precisa de comentário dizendo por quê.

## Testes

- Um teste novo segue o estilo dos vizinhos no mesmo arquivo.
- Verifique se o comportamento já não está coberto antes de acrescentar.
- Fixtures de página vêm de `tests/support`. Um duplo que tenha propriedade que
  a produção não tem certifica comportamento que não existe: prefira uma view
  real sobre um PDF mínimo.
- Marcadores: `slow` (rede ou binário externo), `contract` (suíte de Protocol),
  `integration` (motor real), `real` (PDF público baixado). A CI completa
  roda tudo menos `real`, que depende da rede.
- Um leitor novo herda `ReaderContract` e fornece a fixture `reader`.

## Dependências

- O núcleo instala com pydantic, pypdfium2 e pillow. Nada
  mais entra nele sem que o caminho principal quebre sem ele.
- Cada backend é um extra, e o nome do extra coincide com o nome registrado.
  Um motor alternativo de um backend é um extra com o nome do motor
  (`openvino`). O `onnxruntime-gpu` não vira extra: ele e o `onnxruntime`
  ocupam o mesmo módulo, e quem usa GPU troca um pelo outro.
- `uv.lock` é a fonte da reprodutibilidade: fixa versão e hash de cada pacote, e
  a CI instala com `--locked`, que falha se o lock não bate com o `pyproject`.
- Nada entra com menos de 7 dias: `exclude-newer`, `cooldown` e hash nas actions e nos hooks
  (`SECURITY.md`). Não contorne a janela sem exceção escrita, com motivo e data.
- `uv lock --upgrade-package <nome>` para subir uma só; `--upgrade` para todas.

## Commits

- Nada vai direto para a `main`: toda mudança entra por pull request, e quem junta é o dono.
- Assunto em minúsculas, no imperativo, sem ponto final.
- O corpo explica o porquê. Se houve medição, cite o número e a condição.
- Não descreva o processo de chegar à mudança, descreva a mudança.
