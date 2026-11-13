# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""As políticas de triagem embutidas.

`all_cheap` nunca escala e `all_strong` escala tudo: juntos delimitam a faixa de
qualidade. `evidence` escala só onde a leitura barata provou ter falhado. Os
três se resolvem pelo nome. A linha de base ao acaso, contra a qual o ganho
de uma cascata se mede por fora, e não por uma política.
"""

from __future__ import annotations

import datetime
import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from docaudit.backends.textlayer import TextLayerReader
from docaudit.types import BBox, Entity, EntityState, RoutingDecision, Substrate, Tier

if TYPE_CHECKING:
    from collections.abc import Callable, Container, Mapping, Sequence

    from docaudit.types import Budget, Chunk, Page

__all__ = [
    "AMOUNT_BRL",
    "AMOUNT_IN_WORDS",
    "AMOUNT_PRE_REAL",
    "ARRECADACAO",
    "BOLETO",
    "CNH",
    "CNJ",
    "CNPJ",
    "CPF",
    "DATE_DMY",
    "DATE_VERBOSE",
    "DATE_WEEKDAY",
    "DEFAULT_CHECKS",
    "DEFAULT_ENTITIES",
    "DEFAULT_SIGNALS",
    "DEFAULT_STAMPS",
    "EPROC_STAMP",
    "ESAJ_STAMP",
    "FOLHA",
    "FOLHA_FORMATS",
    "IDENTIFIERS",
    "NFE_KEY",
    "PIS",
    "PJE_STAMP",
    "PROJUDI_GO_STAMP",
    "PROJUDI_PAGE",
    "PROJUDI_PR_STAMP",
    "RENAVAM",
    "STAMP_FORMATS",
    "VOTER_ID",
    "AllCheap",
    "AllStrong",
    "Check",
    "EmptyRead",
    "EvidenceRouter",
    "FailsCheck",
    "GarbledText",
    "LineSignal",
    "MojibakeText",
    "Signal",
    "StampFormat",
    "entities_of",
    "failures",
    "fold_lookalikes",
    "garbled_runs",
    "get_policy",
    "mojibake_in",
    "signal",
]


def _decisions(pages: Sequence[Page], chosen: Container[int], reason: str) -> list[RoutingDecision]:
    """Emite uma decisão por página: STRONG para as de `chosen`, CHEAP para o resto.

    As políticas embutidas diferem só em como calculam `chosen`; isto é tudo
    o que elas têm em comum.
    """
    return [
        RoutingDecision(
            page=p.index,
            tier=Tier.STRONG if p.index in chosen else Tier.CHEAP,
            reason=reason,
        )
        for p in pages
    ]


class AllCheap:
    """Não encaminha nenhuma página."""

    name = "all_cheap"
    needs_reads = False
    signals: tuple[Signal, ...] = ()
    checks: tuple[FailsCheck, ...] = ()

    def decide(
        self,
        pages: Sequence[Page],
        budget: Budget,
        reads: Mapping[int, Sequence[Chunk]] | None = None,
    ) -> Sequence[RoutingDecision]:
        """Marca toda página como CHEAP."""
        del budget, reads
        return _decisions(pages, frozenset[int](), "política all_cheap")


class AllStrong:
    """Encaminha todas as páginas; o teto de `Budget`, quando há, é aplicado por `process`."""

    name = "all_strong"
    needs_reads = False
    signals: tuple[Signal, ...] = ()
    checks: tuple[FailsCheck, ...] = ()

    def decide(
        self,
        pages: Sequence[Page],
        budget: Budget,
        reads: Mapping[int, Sequence[Chunk]] | None = None,
    ) -> Sequence[RoutingDecision]:
        """Marca toda página como STRONG."""
        del budget, reads
        return _decisions(pages, {p.index for p in pages}, "política all_strong")


# ── Evidência de que a leitura barata falhou ─────────────────────────────────
# Todos os sinais são categóricos: nenhum depende de limiar ajustado em corpus.
# O único número da política é `EvidenceRouter(min_failures=)`, não calibrado.

_ID_PUNCTUATION = re.compile(r"[.,\-/]")
_CNPJ_WEIGHTS = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_INTEGER_PART = r"(?:[0-9]{1,3}(?:\.[0-9]{3})*|[0-9]+)"
_WELL_FORMED_AMOUNT = re.compile(_INTEGER_PART + r",[0-9]{2}")
_WELL_FORMED_PRE_REAL = re.compile(_INTEGER_PART + r"(?:,[0-9]{2})?")
_PRE_REAL_SYMBOL = re.compile(r"(?:NCr|Cr|CR|NCz|Cz)\$")

# Hífen e travessões tipográficos, sinal de menos, espaços tipográficos e as
# formas de largura total que um modelo treinado em chinês escreve.
_LOOKALIKES = {
    **dict.fromkeys(range(0x2010, 0x2016), "-"),
    0x2212: "-",
    0xFE58: "-",
    0xFE63: "-",
    **dict.fromkeys((0x00A0, 0x202F, 0x205F, 0x3000, *range(0x2000, 0x200B)), " "),
    **{code: chr(code - 0xFEE0) for code in range(0xFF01, 0xFF5F)},
}


def fold_lookalikes(text: str) -> str:
    """Troca hífens, espaços e formas de largura total tipográficos pelo ASCII.

    Um CPF com o hífen U+2010 no lugar do ASCII passa a casar com a forma. O
    texto sai com o mesmo comprimento, e a posição de cada caractere não muda:
    uma ocorrência achada no texto dobrado aponta para o mesmo trecho do
    original.
    """
    return text.translate(_LOOKALIKES)


@dataclass(frozen=True)
class Check:
    r"""Um campo que o documento imprime numa forma fixa e que se verifica sozinho.

    `pattern` casa a forma impressa; `is_valid` diz se o valor casado é
    possível. O sinal `FailsCheck` conta, no texto lido, as ocorrências que
    falham. Para que a falha prove leitura errada, duas regras:

    - `pattern` casa só a forma daquele campo. Onze dígitos soltos como CPF
      disparariam em todo telefone e protocolo;
    - `is_valid` aceita todo valor verdadeiro. É uma regra de estrutura, como
      um dígito verificador ou o calendário.

    Um campo que só o rótulo distingue de outro número, como o registro da
    CNH, põe o rótulo em `pattern` e o valor num grupo chamado `value`: a
    verificação e a entidade ficam só com o valor.

    Qualquer função `str -> bool` serve, inclusive as `is_valid` do
    python-stdnum, que aceitam o valor com a pontuação:

    ```python
    from stdnum import iban

    IBAN = Check("IBAN", re.compile(r"\bBR\d{2}[0-9A-Z]{25}\b"), iban.is_valid, redundant=True)
    policy = EvidenceRouter([*DEFAULT_SIGNALS, FailsCheck(IBAN)])
    ```
    """

    name: str
    """O nome do campo, como aparece no motivo da decisão e em `Entity.kind`."""
    pattern: re.Pattern[str]
    """A forma impressa do campo."""
    is_valid: Callable[[str], bool]
    """Se o valor, como casou com `pattern`, é possível."""
    redundant: bool = False
    """Se a regra tem redundância que confirma o valor, como um dígito verificador.

    Com `True`, o valor que confere sai `confirmed` em `Result.entities`; com
    `False`, a regra só diz que a forma é possível, e o valor sai
    `well_formed`. Um valor em reais bem escrito pode ter um dígito trocado;
    um CPF com os dois dígitos verificadores certos quase nunca.
    """
    labeled: re.Pattern[str] | None = None
    """A forma depois do rótulo do campo, com o valor no grupo `value`.

    Um id que o documento imprime fora da pontuação padrão, como `CPF:
    22279745836` ou `CNPJ: 61405858/0001-20`, só é id porque o rótulo diz.
    O valor conta só onde `pattern` não casou, sai em `Result.entities`, e
    não encaminha a página: `FailsCheck` olha só `pattern`.
    """
    alike: Callable[[str], bool] | None = None
    """Se o valor que falha é uma troca que leitores de famílias diferentes fazem igual.

    Duas famílias que leem o mesmo valor inválido provam, em geral, que o erro
    está impresso. Nesta troca não provam: os leitores de pixels erram juntos.
    A página segue ao leitor caro, e a entidade sai sem `printed`, salvo quando
    o valor está em texto composto.
    """
    bare: bool = False
    """Se o campo é o valor em reais, que a coluna de uma tabela imprime sem `R$`.

    Com `True`, o número com vírgula decimal e milhar com ponto conta como
    valor do campo mesmo sem o símbolo. A releitura que o traz com os mesmos
    dígitos explica a falha, a linha do leitor caro que o perde é recusada, e
    a camada oculta que lê outro número no lugar fica ao lado da linha.
    Sem nenhuma verificação com `True`, esse número não conta.
    """
    unproven: Callable[[str], bool] | None = None
    """Se um valor que confere fica sem prova, mesmo com `redundant`.

    A redundância de alguns campos não cobre todo valor. O CNPJ com letra
    confere igual ao CNPJ com o dígito que a letra substituiu, e o valor por
    extenso sem número entre parênteses não compara nada. O valor assim sai
    `well_formed`, e a linha da camada oculta que o traz não entra no lugar
    da linha dos pixels.
    """

    def proves(self, value: str) -> bool:
        """Se a redundância da regra prova `value`, que já confere: `redundant` e não `unproven`."""
        return self.redundant and not (self.unproven is not None and self.unproven(value))


def _check_digit(chars: str, weights: Sequence[int]) -> int:
    # Cada posição vale o código do caractere menos 48: o dígito vale ele
    # mesmo, e a letra do CNPJ alfanumérico vale de 17 (A) a 42 (Z).
    rest = sum((ord(c) - 48) * w for c, w in zip(chars, weights, strict=True)) % 11
    return 0 if rest < 2 else 11 - rest


def _cpf_is_valid(printed: str) -> bool:
    digits = _ID_PUNCTUATION.sub("", printed)
    if not digits.isascii() or not digits.isdigit() or len(set(digits)) == 1:
        return False
    return _check_digit(digits[:9], range(10, 1, -1)) == int(digits[9]) and _check_digit(
        digits[:10], range(11, 1, -1)
    ) == int(digits[10])


def _cnpj_is_valid(printed: str) -> bool:
    digits = _ID_PUNCTUATION.sub("", printed)
    if _CNPJ_BODY.fullmatch(digits[:12]) is None or not digits[12:].isdigit():
        return False
    if len(set(digits)) == 1:
        return False
    return _check_digit(digits[:12], _CNPJ_WEIGHTS) == int(digits[12]) and _check_digit(
        digits[:13], (6, *_CNPJ_WEIGHTS)
    ) == int(digits[13])


def _cnpj_has_letter(printed: str) -> bool:
    # Cada letra vale, módulo 11, o mesmo que um dígito, salvo E e P, que valem
    # o mesmo entre si: trocar a letra por esse dígito não muda o verificador.
    return any(c.isalpha() for c in _ID_PUNCTUATION.sub("", "".join(printed.split()))[:12])


def _cnj_is_valid(printed: str) -> bool:
    digits = _ID_PUNCTUATION.sub("", printed)
    if not digits.isascii() or not digits.isdigit():
        return False
    return int(digits[:7] + digits[9:] + digits[7:9]) % 97 == 1


_LEDGER_SUFFIX = re.compile(r"\s+[CD]$")


def _amount_brl_is_valid(printed: str) -> bool:
    number = _LEDGER_SUFFIX.sub("", printed.removeprefix("R$").removeprefix("RS").lstrip())
    return _WELL_FORMED_AMOUNT.fullmatch(number) is not None


def _amount_brl_decimal_point(printed: str) -> bool:
    return _amount_brl_is_valid(re.sub(r"\.([0-9]{2})$", r",\1", printed))


def _amount_pre_real_is_valid(printed: str) -> bool:
    figure = _PRE_REAL_SYMBOL.sub("", printed, count=1).lstrip()
    return _WELL_FORMED_PRE_REAL.fullmatch(figure) is not None


# Nas posições de dígito, a forma impressa de um id aceita também letra: a
# troca de dígito por letra parecida (`0` lido `o`, `1` lido `l`, `5` lido `S`)
# é comum, e com uma forma só de dígitos o valor
# lido errado nem casava. Casando, a regra o recusa, porque nenhum id
# verdadeiro tem letra ali. O lookahead pede ao menos um dígito de verdade.
# Os dígitos são `[0-9]`: em Python, `\d` casa também dígitos de outros
# sistemas de escrita, e o dígito verificador conta só os de 0 a 9.
_SLOT = "[0-9A-Za-z]"
# O ponto dos ids: o OCR o lê como vírgula, e o dígito verificador decide.
_DOT = "[.,]"
_HAS_DIGIT = r"(?=[0-9A-Za-z.\-/]*[0-9])"
# Um ponto, hífen ou barra antes do valor só o liga a um número maior se vier
# logo depois de uma posição de dígito, que aceita letra pela mesma razão do
# `_SLOT`: `n°/123.456.789-09` e `n°.12.345.678/0001-90` são o valor depois de
# um rótulo. É a mesma regra que o fim do valor já segue.
_AFTER_DIGIT = "(?<![0-9])(?<![0-9A-Za-z]{sep})"
_CNPJ_BODY = re.compile("[0-9A-Z]{12}")

# Numa tabela, a data da coluna seguinte encosta no id quando o OCR perde o
# espaço entre as colunas: `889-0011/12/1972`. Dois dígitos e uma barra depois
# do valor são o começo dessa data, não um número maior. Vale para os três ids,
# e `DATE_DMY` acha a data do outro lado da mesma emenda.
_GLUED_DATE = r"(?=[0-3][0-9]/[01][0-9]/[0-9]{2})"

# O rótulo do campo e o valor com um ponto, traço, barra ou espaço entre
# quaisquer dígitos. O rótulo admite `CPF`, `C.P.F.`, `CPF/MF`, `nº` e
# dois-pontos ou traço antes do valor.
_LABEL_TAIL = (
    r"\.?(?:[^\S\n]*/[^\S\n]*(?i:m\.?f)\.?)?[^\S\n]*"
    r"(?:(?i:n)[º°o]\.?[^\S\n]*)?[:.\-]?[^\S\n]*"
)
_CPF_LABELED = re.compile(
    r"(?<![^\W\d_])(?i:c\.?[^\S\n]?p\.?[^\S\n]?f)"
    + _LABEL_TAIL
    + r"(?P<value>(?:[0-9][.\-/ ]?){10}[0-9])(?!\d)"
)
_CNPJ_LABELED = re.compile(
    r"(?<![^\W\d_])(?i:c\.?[^\S\n]?n\.?[^\S\n]?p\.?[^\S\n]?j)"
    + _LABEL_TAIL
    + r"(?P<value>(?:[0-9][.\-/ ]?){13}[0-9])(?!\d)"
)

CPF = Check(
    "CPF",
    re.compile(
        _AFTER_DIGIT.format(sep=r"[.\-/]")
        + rf"{_HAS_DIGIT}{_SLOT}{{3}}{_DOT}{_SLOT}{{3}}{_DOT}{_SLOT}{{3}}-{_SLOT}{{2}}"
        + rf"(?:(?![\d\-/])|{_GLUED_DATE})"
    ),
    _cpf_is_valid,
    redundant=True,
    labeled=_CPF_LABELED,
)
"""CPF na pontuação canônica, pelos dois dígitos verificadores em módulo 11.

A forma aceita letra nas posições de dígito, e a regra a recusa: `529.982.247-2S`
é um CPF lido errado, e não texto qualquer. Aceita também vírgula no lugar de
ponto, como CNPJ e CNJ, e a data da coluna seguinte colada logo depois.
"""
CNPJ = Check(
    "CNPJ",
    re.compile(
        r"(?<!\w)(?<!\w[.\-/])"
        + rf"{_HAS_DIGIT}{_SLOT}{{2}}{_DOT}{_SLOT}{{3}}{_DOT}{_SLOT}{{3}}/{_SLOT}{{4}}-{_SLOT}{{2}}"
        + rf"(?:(?![\w\-/])|{_GLUED_DATE})"
    ),
    _cnpj_is_valid,
    redundant=True,
    labeled=_CNPJ_LABELED,
    unproven=_cnpj_has_letter,
)
"""CNPJ numérico ou alfanumérico.

Desde a IN RFB 2.229/2024, as doze primeiras posições aceitam letra maiúscula,
e cada caractere vale o código menos 48 no módulo 11. Caracteres de mesmo valor
módulo 11 trocam sem mudar o dígito verificador: O e D, 0 e Q, 2 e S, 8 e N.
Essa leitura errada passa pela verificação. Toda letra, salvo E e P, vale
módulo 11 o mesmo que um dígito, e E e P valem o mesmo entre si: o CNPJ com
letra que confere sai `well_formed`, e só o numérico sai `confirmed`. Letra
minúscula, ou letra nos dois dígitos verificadores, é sempre leitura errada.
Vírgula no lugar de ponto é a troca de pontuação que o OCR faz, e casa.
"""
CNJ = Check(
    "CNJ",
    re.compile(
        _AFTER_DIGIT.format(sep=r"[.\-]")
        + rf"{_HAS_DIGIT}{_SLOT}{{7}}-{_SLOT}{{2}}{_DOT}{_SLOT}{{4}}"
        + rf"{_DOT}{_SLOT}{_DOT}{_SLOT}{{2}}{_DOT}{_SLOT}{{4}}"
        + rf"(?:(?!\d)(?![.\-]\d)|{_GLUED_DATE})"
    ),
    _cnj_is_valid,
    redundant=True,
)
"""Número único de processo, NNNNNNN-DD.AAAA.J.TR.OOOO.

Pela Resolução CNJ 65/2008 (ISO 7064, módulo 97 base 10): com os dígitos
verificadores levados para o fim, o número deixa resto 1 na divisão por 97. Um
ponto ou hífen logo depois só continua o número se vier seguido de dígito. A
vírgula no lugar de um ponto interno casa, como no CPF e no CNPJ.
"""
AMOUNT_BRL = Check(
    "valor em reais",
    re.compile(
        r"(?<![A-Za-z])R\$[^\S\n]*\n?[^\S\n]*(?=[0-9A-Za-z.]*[0-9])[0-9A-Za-z][0-9A-Za-z.]*,[0-9A-Za-z]{2}(?![\w,])(?!\.\d)"
        r"|(?<![A-Za-z])RS[^\S\n]*\n?[^\S\n]*" + _WELL_FORMED_AMOUNT.pattern + r"(?![\w,])(?!\.\d)"
        r"|\b[0-9]{1,3}(?:,[0-9]{3})+,[0-9]{2}\b"
        r"|\b[0-9]{1,3}(?:[ :][0-9]{3})+[,.][0-9]{2}\b"
        r"|(?<![\d.,])[0-9]{1,3}(?:\.[0-9]{3})+\.[0-9]{2}(?![\d.,])"
        r"|(?<![A-Za-z])R\$[^\S\n]*[0-9]{1,3}(?:\.[0-9]{3})*\.[0-9]{2}(?![\d.,])"
        r"|(?m:^[^\S\n]*[0-9]{1,3}(?:\.[0-9]{3})*\.[0-9]{2}[^\S\n]*$)"
        r"|(?<![\w.,])(?=[0-9A-Za-z.]{0,4}[0-9])[0-9A-Za-z]{1,3}(?:\.[0-9A-Za-z]{3})*,[0-9A-Za-z]{2}"
        r"[^\S\n]+[CD](?![^\W\d_])"
    ),
    _amount_brl_is_valid,
    alike=_amount_brl_decimal_point,
    bare=True,
)
"""Valor em reais.

Casa o valor depois de `R$`, separado por espaços e no máximo uma quebra de
linha, com o que o motor tiver posto no lugar dos dígitos,
o valor com duas vírgulas, o valor com espaço ou dois-pontos entre grupos e
o valor com ponto no lugar da vírgula decimal, `4.329.30`. O `RS` no lugar
do `R$` é a troca que um leitor de pixels faz no cifrão, e casa só seguido
de um número bem escrito: `RS 1.234,56` é valor, a sigla do estado não é.
Falham a letra no lugar de dígito (`R$ 1.O00,00`), o grupo de milhar sem três
dígitos (`R$ 1.00,00`), as duas vírgulas (`5,837,52`), o espaço entre grupos
e o ponto decimal. O ponto decimal casa depois do milhar (`4.329.30`), logo
depois do `R$` (`R$ 18.77`) e no valor sozinho na linha (`0.00`), a célula de
uma tabela. É a troca que os leitores de pixels fazem na vírgula de uma
tabela digitalizada, e fazem juntos: por isso ela é `alike`, e outra família
que lê o mesmo ponto não prova que ele está impresso. O documento que imprime
o valor assim vai ao leitor caro. Na página nascida digital, o número com
ponto sozinho na linha, como uma taxa de uma tabela, sai `failed` e impresso
pela camada de texto.

O extrato bancário e o livro contábil não imprimem o `R$`: a coluna diz a
moeda, e cada lançamento termina em `C` ou `D`, crédito ou débito. O valor
seguido de um espaço e dessa letra maiúscula casa, `1.249,01 C`, e sai com
o sufixo. A letra precisa ser a última da palavra: `12,50 Cada` não é
lançamento. O valor sem `R$` e sem o sufixo não casa: nada o separa de um
número qualquer.
"""

AMOUNT_PRE_REAL = Check(
    "valor em moeda anterior ao real",
    re.compile(
        r"(?<![A-Za-z])" + _PRE_REAL_SYMBOL.pattern + r"[^\S\n]*\n?[^\S\n]*"
        r"(?=[0-9A-Za-z.]*[0-9])[0-9A-Za-z][0-9A-Za-z.]*(?:,[0-9A-Za-z]{2})?(?![\w,])(?!\.\d)"
    ),
    _amount_pre_real_is_valid,
)
"""Valor em cruzeiro (`Cr$`, `NCr$`), cruzado (`Cz$`, `NCz$`) ou cruzeiro real (`CR$`).

As moedas anteriores ao Real, de 1942 a 1994, aparecem nos autos antigos e
nos valores antigos citados em peças novas. A grafia é a do real, com os
centavos opcionais: o valor redondo em cruzeiros costuma vir sem eles. O
valor sai como impresso, com o símbolo, e quem o lê sabe a moeda. Falham a
letra no lugar de dígito e o grupo de milhar sem três dígitos. O `R$` de
`AMOUNT_BRL` não casa dentro de `CR$`.
"""


def _calendar(year: int, month: int | None, day: int) -> datetime.date | None:
    """A data do calendário, ou `None` quando ela não existe."""
    if month is None:
        return None
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def _date_exists(printed: str) -> bool:
    day, month, year = (int(part) for part in printed.split("/"))
    return _calendar(year, month, day) is not None


FOLHA = Check(
    "folha",
    re.compile(
        r"(?<![^\W\d_])(?i:fls?)(?:[.:][^\S\n]*|[^\S\n]+)(?:(?i:n)[º°o]\.?[^\S\n]*)?"
        r"(?P<number>[0-9]{1,3}(?:\.[0-9]{3})+|[0-9]+)"
        r"(?P<verso>[^\S\n]*[vV](?:[º°o]\.?|\.|(?![^\W\d_])))?"
        r"(?![0-9/])(?!\.[0-9])"
    ),
    lambda _: True,
)
"""A folha dos autos, `fl. 16`, `fls. 5.662` ou `fls: 1002`, como o tribunal a carimba.

As peças a citam da mesma forma. O carimbo do e-SAJ escreve a folha de
quatro dígitos sem ponto de milhar, e o de sistemas antigos usa dois-pontos:
as duas formas casam. O verso (`fls. 9494vº`, `fls. 13 v.`) fica no valor.

`fl` precisa de separador antes do número: sem isso, o código de conferência
da tarja do e-SAJ (`código fL8lW7AI`) leria a folha 8.

Não tem regra de validade: todo valor sai `well_formed`. Entra em
`DEFAULT_ENTITIES` porque é a coordenada que quem lê um auto cita, e a página
da fonte não é a folha: o carimbo no alto da página é a folha dela, e a
citação no corpo aponta para outra. O carimbo, em linha de elemento fixo,
vai em `Page.folha`.
Um intervalo, `fls. 08/10`, não casa: o valor seria só a primeira folha.
"""

DATE_DMY = Check(
    "data",
    # Depois de um dígito, só a data colada ao fim de um id: `-DD` do CPF e do
    # CNPJ, `.OOOO` do CNJ.
    re.compile(
        r"(?:(?<![\d/])|(?<=-[0-9A-Za-z]{2})|(?<=[.,][0-9]{4}))"
        r"[0-9]{2}/[0-9]{2}/[0-9]{4}(?![\d/])"
    ),
    _date_exists,
)
"""Data dd/mm/aaaa que existe no calendário.

Entra em `DEFAULT_ENTITIES`, e não em `DEFAULT_SIGNALS`: uma data impossível
costuma estar impressa assim no documento, e reler devolveria o mesmo valor.
Como entidade, diz onde cada data está e se ela existe.
"""


_WEEKDAYS = {
    name: n
    for n, name in enumerate(["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"])
}
_MONTHS = {
    name: n
    for n, name in enumerate(
        [
            "janeiro",
            "fevereiro",
            "marco",
            "abril",
            "maio",
            "junho",
            "julho",
            "agosto",
            "setembro",
            "outubro",
            "novembro",
            "dezembro",
        ],
        start=1,
    )
}
_WEEKDAY_DATE = re.compile(
    r"(?i)\b(segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo)(?:-feira)?,?[^\S\n]*\n?[^\S\n]*"
    r"(?:([0-9]{1,2})[º°]?[^\S\n]+de[^\S\n]+([a-zç]+)[^\S\n]+de[^\S\n]+|([0-9]{2})/([0-9]{2})/)"
    r"([0-9]{4})(?![\d/])"
)


def _plain(word: str) -> str:
    """A palavra em minúsculas e sem acento: `Terça` vira `terca`, `Março` vira `marco`."""
    decomposed = unicodedata.normalize("NFD", word.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _weekday_matches(printed: str) -> bool:
    match = _WEEKDAY_DATE.fullmatch(printed)
    if match is None:
        return False
    weekday, day, name, dd, mm, year = match.groups()
    date = _calendar(int(year), int(mm) if mm else _MONTHS.get(_plain(name)), int(day or dd))
    return date is not None and date.weekday() == _WEEKDAYS[_plain(weekday)]


DATE_WEEKDAY = Check("data com dia da semana", _WEEKDAY_DATE, _weekday_matches)
"""A data impressa com o dia da semana, por extenso ou `dd/mm/aaaa`.

Cabeçalhos de diário oficial e fechos de decisão imprimem assim:
`Quarta-feira, 05 de Janeiro de 2022`, `segunda-feira, 10/03/2025`.

O dia da semana que não confere com o calendário prova a leitura errada, e a
data sai `failed`. O que confere não prova a leitura certa: o dia da semana
se repete a cada sete dias, e `17/03/2025` lido no lugar de `10/03/2025`
passa. Por isso a regra não tem redundância, e a data que confere sai
`well_formed`. A data `dd/mm/aaaa` com o dia na frente sai também como
`data`, que só diz que ela existe. O dia e a data podem estar em linhas
seguidas.
"""

# Os meses de `_MONTHS`, com o cedilha opcional de março.
_MONTH_NAMES = "(?:" + "|".join(name.replace("marco", "mar[çc]o") for name in _MONTHS) + ")"
_VERBOSE_DATE = re.compile(
    r"(?i)(?<![\d/.,\-])([0-9]{1,2})[º°]?[^\S\n]*\n?[^\S\n]*de[^\S\n]*\n?[^\S\n]*"
    rf"({_MONTH_NAMES})[^\S\n]*\n?[^\S\n]*de[^\S\n]*\n?[^\S\n]*([0-9]{{4}})(?![\d/])"
)


def _verbose_date_exists(printed: str) -> bool:
    match = _VERBOSE_DATE.fullmatch(printed)
    if match is None:
        return False
    day, name, year = match.groups()
    return _calendar(int(year), _MONTHS.get(_plain(name)), int(day)) is not None


DATE_VERBOSE = Check("data por extenso", _VERBOSE_DATE, _verbose_date_exists)
"""A data por extenso, `15 de janeiro de 2024`, que existe no calendário.

É a data do fecho de uma peça, de um contrato e de uma certidão: `São
Paulo, 1º de março de 2024`. O mês vale em qualquer caixa e com ou sem o
cedilha de março; a palavra que não é mês não casa. O dia, o mês e o ano
podem estar em linhas seguidas.

Sem redundância: sai `well_formed`, como `DATE_DMY`, e pela mesma razão
não entra em `DEFAULT_SIGNALS`. A data com o dia da semana na frente sai
também como `DATE_WEEKDAY`, que a recusa quando o dia não confere.
"""


# ── Valor por extenso ───────────────────────────────────────────────────────
# Os números por extenso do português, com as grafias que os documentos usam:
# "quatorze" e "catorze", "hum", "um mil", "duzentas". Palavras sem acento.
_UNITS = {
    "zero": 0, "um": 1, "uma": 1, "hum": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4,
    "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12,
    "treze": 13, "quatorze": 14, "catorze": 14, "quinze": 15, "dezesseis": 16,
    "dezessete": 17, "dezoito": 18, "dezenove": 19, "vinte": 20, "trinta": 30,
    "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70, "oitenta": 80,
    "noventa": 90, "cem": 100, "cento": 100, "duzentos": 200, "duzentas": 200,
    "trezentos": 300, "trezentas": 300, "quatrocentos": 400, "quatrocentas": 400,
    "quinhentos": 500, "quinhentas": 500, "seiscentos": 600, "seiscentas": 600,
    "setecentos": 700, "setecentas": 700, "oitocentos": 800, "oitocentas": 800,
    "novecentos": 900, "novecentas": 900,
}  # fmt: skip
_SCALES = {"mil": 1_000, "milhao": 10**6, "milhoes": 10**6, "bilhao": 10**9, "bilhoes": 10**9}
_REAIS = {"real", "reais"}
_CENTAVOS = {"centavo", "centavos"}
_JOINERS = {"e", "de"}


def _bare_words(text: str) -> list[str]:
    """As palavras em minúsculas, sem acento, com a palavra partida em fim de linha juntada."""
    return re.findall(r"[a-z]+", _plain(re.sub(r"-\s*\n\s*", "", text)))


def _rank(value: int) -> int:
    """A ordem de grandeza de uma palavra de número: centena, dezena ou unidade."""
    return 3 if value >= 100 else 2 if value >= 20 else 1


def _words_to_int(words: list[str]) -> int | None:
    """O número escrito em `words`, ou None se as palavras não formam um número.

    Segue a ordem com que o português escreve: em cada grupo antes de "mil",
    "milhão" ou "bilhão", a centena, depois a dezena, depois a unidade, cada
    uma no máximo uma vez, e "cem" só sozinho. As escalas descem: "mil mil" e
    "mil milhões" não são números. Uma palavra que não é de número também
    devolve None.
    """
    total = group = 0
    last_rank = 4  # acima de qualquer palavra: o grupo começa vazio
    last_scale = 10**12
    seen = False
    for word in words:
        if word in _JOINERS:
            continue
        if word in _UNITS:
            value = _UNITS[word]
            rank = _rank(value)
            # Depois de uma dezena só vem unidade de um a nove: "vinte e doze" não existe.
            if rank >= last_rank or (last_rank == 2 and value >= 10):
                return None
            group += value
            # "cem" é cem e nada mais: depois dele, o grupo está fechado.
            last_rank = 1 if word == "cem" else rank
        elif word in _SCALES:
            scale = _SCALES[word]
            if scale >= last_scale:
                return None
            total += (group or 1) * scale
            group, last_rank, last_scale = 0, 4, scale
        else:
            return None
        seen = True
    return total + group if seen else None


def _spelled_cents(text: str) -> int | None:
    """O valor por extenso em centavos, ou None se o texto não é só um valor por extenso."""
    words = _bare_words(text)
    reais = [i for i, w in enumerate(words) if w in _REAIS]
    centavos = [i for i, w in enumerate(words) if w in _CENTAVOS]
    if not reais and not centavos:
        return None
    if reais:
        whole = _words_to_int(words[: reais[0]])
        rest = words[reais[0] + 1 :]
    else:
        whole, rest = 0, words
    if whole is None:
        return None
    if not rest:
        return whole * 100
    if not centavos or centavos[-1] != len(words) - 1:
        return None
    cents = _words_to_int(rest[:-1])
    return None if cents is None else whole * 100 + cents


def _amount_in_words_pair(printed: str) -> tuple[int, int] | None:
    """O número e o extenso em centavos, ou None quando não há os dois para comparar.

    A grafia do número é de `AMOUNT_BRL`, e um parêntese que não é só um valor
    por extenso não diz nada.
    """
    digits, _, spelled = printed.partition("(")
    figure = digits.removeprefix("R$").strip()
    words = _spelled_cents(spelled.removesuffix(")"))
    if _WELL_FORMED_AMOUNT.fullmatch(figure) is None or words is None:
        return None
    return int(re.sub(r"[.,]", "", figure)), words


def _amount_in_words_is_valid(printed: str) -> bool:
    pair = _amount_in_words_pair(printed)
    return pair is None or pair[0] == pair[1]


def _amount_in_words_unproven(printed: str) -> bool:
    return _amount_in_words_pair(printed) is None


AMOUNT_IN_WORDS = Check(
    "valor por extenso",
    re.compile(
        r"R\$\s?[0-9A-Za-z][0-9A-Za-z.,]*\s*\((?=[^()]*(?:rea[li]s?|centavos?))[^()]{3,300}\)"
    ),
    _amount_in_words_is_valid,
    redundant=True,
    unproven=_amount_in_words_unproven,
)
"""Valor em reais seguido do mesmo valor por extenso, entre parênteses.

Os dois têm de ser o mesmo número: `R$ 214.000,00 (duzentos e quatorze mil
reais)`. Uma troca de dígito que forma outro valor bem escrito passa pela
grafia, e não passa por aqui. Fica sem evidência o parêntese que não é só um
valor por extenso, como `(sem os acréscimos legais)`, e o número mal escrito,
que é de `AMOUNT_BRL`: não falha, e sai `well_formed`. Um documento que
imprime os dois diferentes também dispara: é o falso positivo conhecido.

Não está em `DEFAULT_SIGNALS`. Entra por escolha: `EvidenceRouter([*DEFAULT_SIGNALS,
FailsCheck(AMOUNT_IN_WORDS)])`.
"""


# ── Códigos com dígito verificador ──────────────────────────────────────────
# A chave de acesso, a linha digitável e o código de arrecadação são longos e
# têm mais redundância que um CPF: além do dígito verificador, trazem campos
# de valores fechados. As formas aceitam letra parecida nas posições de dígito,
# como os ids, e a regra recusa a letra.
# O primeiro dígito está no primeiro bloco do código: o lookahead para em doze posições.
_HAS_DIGIT_SPACED = r"(?=[0-9A-Za-z.\- ]{0,12}[0-9])"
# Um ponto antes ou depois só prende o código a um número maior se vier colado a
# um dígito do outro lado: o ponto final de uma frase não o invalida.
_CODE_START = r"(?<![0-9A-Za-z\-/])(?<![0-9A-Za-z]\.)"
_CODE_END = r"(?![0-9A-Za-z\-/])(?!\.[0-9A-Za-z])"
_SEPARATORS = re.compile(r"[\s.\-/]")

# Os códigos de UF do IBGE: a chave de acesso começa por um deles.
_UF_CODES = frozenset(
    [
        "11",
        "12",
        "13",
        "14",
        "15",
        "16",
        "17",
        "21",
        "22",
        "23",
        "24",
        "25",
        "26",
        "27",
        "28",
        "29",
        "31",
        "32",
        "33",
        "35",
        "41",
        "42",
        "43",
        "50",
        "51",
        "52",
        "53",
    ]
)
# Os modelos dos documentos fiscais eletrônicos com chave de 44 dígitos: NF-e,
# CT-e, MDF-e, CF-e-SAT, NFCom, BP-e, NFC-e, NF3e e CT-e OS.
_DFE_MODELS = frozenset({"55", "57", "58", "59", "62", "63", "65", "66", "67"})
# Os pesos 2 a 9 da direita para a esquerda, como `_check_digit` os lê, da esquerda.
_NFE_WEIGHTS = tuple(2 + i % 8 for i in reversed(range(43)))


def _weighted_sum(digits: str) -> int:
    """A soma dos dígitos vezes os pesos 2 a 9, repetidos da direita para a esquerda."""
    return sum(int(d) * (2 + i % 8) for i, d in enumerate(reversed(digits)))


def _mod10_dac(digits: str) -> int:
    """O dígito módulo 10 da FEBRABAN: pesos 2 e 1 da direita, soma dos algarismos dos produtos."""
    total = 0
    for i, d in enumerate(reversed(digits)):
        product = int(d) * (2 if i % 2 == 0 else 1)
        total += product if product < 10 else product - 9
    return (10 - total % 10) % 10


def _mod11_febraban(digits: str) -> int:
    """O dígito módulo 11 da arrecadação: resto 0 ou 1 dá 0, resto 10 dá 1."""
    rest = _weighted_sum(digits) % 11
    if rest in (0, 1):
        return 0
    return 1 if rest == 10 else 11 - rest


def _mod11_boleto(digits: str) -> int:
    """O dígito geral do boleto: 11 menos o resto, e 0, 10 ou 11 viram 1."""
    dv = 11 - _weighted_sum(digits) % 11
    return 1 if dv in (0, 10, 11) else dv


def _all_digits(printed: str, *lengths: int) -> str | None:
    """Os dígitos de um valor impresso, se são só dígitos ASCII e num dos comprimentos dados."""
    digits = _SEPARATORS.sub("", printed)
    if len(digits) not in lengths or not digits.isascii() or not digits.isdigit():
        return None
    return digits


def _nfe_key_is_valid(printed: str) -> bool:
    digits = _all_digits(printed, 44)
    if digits is None or _check_digit(digits[:43], _NFE_WEIGHTS) != int(digits[43]):
        return False
    return digits[:2] in _UF_CODES and "01" <= digits[4:6] <= "12" and digits[20:22] in _DFE_MODELS


def _boleto_is_valid(printed: str) -> bool:
    digits = _all_digits(printed, 47)
    if digits is None:
        return False
    fields = (digits[0:10], digits[10:21], digits[21:32])
    if any(_mod10_dac(f[:-1]) != int(f[-1]) for f in fields):
        return False
    # O código de barras, sem o dígito geral: banco e moeda, fator e valor, campo livre.
    barcode = digits[0:4] + digits[33:47] + digits[4:9] + digits[10:20] + digits[21:31]
    return _mod11_boleto(barcode) == int(digits[32])


def _arrecadacao_is_valid(printed: str) -> bool:
    digits = _all_digits(printed, 48)
    if digits is None:
        return False
    blocks = [digits[i : i + 12] for i in range(0, 48, 12)]
    barcode = "".join(b[:11] for b in blocks)
    if barcode[0] != "8" or barcode[2] not in "6789":
        return False
    dac = _mod10_dac if barcode[2] in "67" else _mod11_febraban
    if any(dac(b[:11]) != int(b[11]) for b in blocks):
        return False
    return dac(barcode[:3] + barcode[4:]) == int(barcode[3])


NFE_KEY = Check(
    "chave de acesso",
    re.compile(
        _CODE_START
        + _HAS_DIGIT_SPACED
        + rf"(?:{_SLOT}{{4}}[^\S\n]){{10}}{_SLOT}{{4}}"
        + _CODE_END
        + "|"
        + _CODE_START
        + rf"{_HAS_DIGIT}{_SLOT}{{44}}"
        + _CODE_END
    ),
    _nfe_key_is_valid,
    redundant=True,
)
"""A chave de acesso de um documento fiscal eletrônico: 44 dígitos, juntos ou em grupos de quatro.

A chave traz a UF do emitente, o ano e o mês, o CNPJ, o modelo, a série, o
número, a forma de emissão, um código e o dígito verificador em módulo 11.
Confere o dígito, a UF entre os códigos do IBGE, o mês de 01 a 12 e o
modelo entre os documentos com chave: a leitura errada que preserva o
dígito ainda tem de acertar os três campos fechados. O CNPJ fica de fora:
a nota de pessoa física traz CPF completado com zeros.
"""

BOLETO = Check(
    "linha digitável de boleto",
    re.compile(
        _CODE_START
        + _HAS_DIGIT_SPACED
        + rf"{_SLOT}{{5}}\.?{_SLOT}{{5}}[^\S\n]*{_SLOT}{{5}}\.?{_SLOT}{{6}}[^\S\n]*"
        + rf"{_SLOT}{{5}}\.?{_SLOT}{{6}}[^\S\n]*{_SLOT}[^\S\n]*{_SLOT}{{14}}"
        + _CODE_END
    ),
    _boleto_is_valid,
    redundant=True,
)
"""A linha digitável de um boleto de cobrança: 47 dígitos em cinco campos.

Os três primeiros campos têm cada um o próprio dígito em módulo 10; o
quarto é o dígito geral do código de barras, em módulo 11; o quinto traz o
fator de vencimento e o valor. Os quatro dígitos têm de conferir. Casa com
os pontos e espaços da impressão, `23793.38128 60007.827136 95000.063305
9 84660000026035`, e sem eles.
"""

ARRECADACAO = Check(
    "código de arrecadação",
    re.compile(
        _CODE_START
        + _HAS_DIGIT_SPACED
        + rf"(?:{_SLOT}{{11}}[ \-]?{_SLOT}[^\S\n]*){{3}}{_SLOT}{{11}}[ \-]?{_SLOT}"
        + _CODE_END
    ),
    _arrecadacao_is_valid,
    redundant=True,
)
"""O código de arrecadação de uma guia, conta ou tributo: 48 dígitos em quatro blocos.

É o padrão FEBRABAN de arrecadação, da conta de luz à guia de imposto.
Cada bloco de onze dígitos tem o próprio dígito verificador, e a quarta
posição do código guarda o dígito geral. O terceiro dígito diz o módulo: 6
e 7 em módulo 10, 8 e 9 em módulo 11. O primeiro dígito é sempre 8. Casa
`82660000001-0 20400000600-8 05232500000-8 00000000000-0`, com espaço no
lugar do traço, e os 48 dígitos juntos.
"""


# ── Ids com dígito verificador que entram por escolha ──────────────────────
# O PIS, o título de eleitor, a CNH e o RENAVAM têm forma pública e dígito
# verificador, como o CPF, e aparecem só em certos tipos de documento: a folha
# de pagamento, a procuração, o auto de infração, a penhora de veículo. Fora
# deles, onze dígitos soltos casariam protocolo e telefone, e a política
# `evidence` gastaria o leitor caro numa falha que não é do campo. Ficam fora
# de `DEFAULT_ENTITIES` e entram por `IDENTIFIERS`.
_SP_MG = ("01", "02")


def _pis_is_valid(printed: str) -> bool:
    digits = _all_digits(printed, 11)
    if digits is None or len(set(digits)) == 1:
        return False
    return _check_digit(digits[:10], (3, 2, 9, 8, 7, 6, 5, 4, 3, 2)) == int(digits[10])


PIS = Check(
    "PIS",
    re.compile(
        _CODE_START + rf"{_HAS_DIGIT}{_SLOT}{{3}}\.{_SLOT}{{5}}\.{_SLOT}{{2}}-{_SLOT}" + _CODE_END
    ),
    _pis_is_valid,
    redundant=True,
    labeled=re.compile(
        r"(?<![^\W\d_])(?i:PIS(?:[^\S\n]*/[^\S\n]*PASEP)?|PASEP|NIT|NIS)"
        + _LABEL_TAIL
        + r"(?P<value>(?:[0-9][.\-/ ]?){10}[0-9])(?!\d)"
    ),
)
"""PIS, PASEP ou NIT, `123.45678.90-1`, pelo dígito verificador em módulo 11.

É o número do trabalhador na folha de pagamento, na guia do FGTS e no
processo trabalhista. Depois do rótulo (`PIS/PASEP:`, `NIT`), o valor vale
com qualquer pontuação, como o CPF. Entra por `IDENTIFIERS`.
"""


def _voter_id_is_valid(printed: str) -> bool:
    digits = _all_digits(printed, 12, 13)
    if digits is None:
        return False
    state = digits[-4:-2]
    if not "01" <= state <= "28" or (len(digits) == 13 and state not in _SP_MG):
        return False

    def digit(rest: int) -> int:
        # O resto 10 vira 0, e o resto 0 vira 1 em São Paulo e Minas Gerais.
        return 0 if rest == 10 else (1 if rest == 0 and state in _SP_MG else rest)

    first = digit(sum(int(d) * w for d, w in zip(digits[:8], range(2, 10), strict=True)) % 11)
    second = digit((int(state[0]) * 7 + int(state[1]) * 8 + first * 9) % 11)
    return (first, second) == (int(digits[-2]), int(digits[-1]))


VOTER_ID = Check(
    "título de eleitor",
    re.compile(
        _CODE_START
        + _HAS_DIGIT_SPACED
        + rf"{_SLOT}{{4}}[^\S\n]{_SLOT}{{4}}[^\S\n]{_SLOT}{{4}}"
        + _CODE_END
    ),
    _voter_id_is_valid,
    redundant=True,
    labeled=re.compile(
        r"(?<![^\W\d_])(?i:t[íi]tulo(?:[^\S\n]+de)?[^\S\n]+eleitor(?:al)?"
        r"|inscri[çc][ãa]o[^\S\n]+eleitoral)"
        + _LABEL_TAIL
        + r"(?P<value>(?:[0-9][.\-/ ]?){11,12}[0-9])(?!\d)"
    ),
)
"""Título de eleitor, `1234 5678 0132`, pelos dois dígitos verificadores e pelo código da UF.

São doze dígitos, treze em São Paulo e Minas Gerais: oito de sequência, dois
da unidade da federação, de 01 a 28, e dois verificadores em módulo 11.
A forma é a dos três grupos de quatro com que o documento o imprime; depois
do rótulo (`Título de Eleitor nº`), o valor vale com qualquer pontuação, e é
onde o de treze dígitos entra. Entra por `IDENTIFIERS`.
"""


def _cnh_is_valid(printed: str) -> bool:
    digits = _all_digits(printed, 11)
    if digits is None or len(set(digits)) == 1:
        return False
    values = [int(d) for d in digits]
    first = sum(v * (9 - i) for i, v in enumerate(values[:9])) % 11
    second = sum(v * (i + 1) for i, v in enumerate(values[:9])) % 11
    return (0 if first > 9 else first, 0 if second > 9 else second) == (values[9], values[10])


CNH = Check(
    "CNH",
    re.compile(
        r"(?<![^\W\d_])(?i:CNH|carteira[^\S\n]+nacional[^\S\n]+de[^\S\n]+habilita[çc][ãa]o"
        r"|(?:n[º°o]\.?[^\S\n]*(?:de[^\S\n]+)?)?registro)"
        + _LABEL_TAIL
        + rf"(?P<value>{_HAS_DIGIT}{_SLOT}{{11}})"
        + _CODE_END
    ),
    _cnh_is_valid,
    redundant=True,
)
"""O registro da CNH, onze dígitos depois de `CNH` ou `Registro`, pelos dois dígitos verificadores.

Onze dígitos soltos são também CPF sem pontuação, protocolo e telefone: só o
rótulo diz que é CNH, e por isso ele está na forma, com o valor no grupo
`value`. A regra é a do modelo de 2022. Entra por `IDENTIFIERS`.
"""


def _renavam_is_valid(printed: str) -> bool:
    digits = _all_digits(printed, 11)
    if digits is None or len(set(digits)) == 1:
        return False
    # Os dez primeiros, da direita para a esquerda, pelos pesos 2 a 9 e depois 2 e 3.
    return _check_digit(digits[9::-1], (2, 3, 4, 5, 6, 7, 8, 9, 2, 3)) == int(digits[10])


RENAVAM = Check(
    "RENAVAM",
    re.compile(
        r"(?<![^\W\d_])(?i:RENAVAM)[^\S\n]*(?:(?i:n)[º°o]\.?[^\S\n]*)?[:.\-]?[^\S\n]*"
        + rf"(?P<value>{_HAS_DIGIT}{_SLOT}{{11}})"
        + _CODE_END
    ),
    _renavam_is_valid,
    redundant=True,
)
"""O RENAVAM de um veículo: `RENAVAM`, no máximo `nº` ou dois-pontos, e onze dígitos colados.

É o campo mais fácil de confundir com outro número. O dígito verificador é
um só, em módulo 11: pega todo dígito trocado, mas um número qualquer de
onze dígitos passa por ele uma vez em onze. Por isso a forma é estreita.
O número antigo, de nove dígitos, fica de fora: desde 2013 todo documento o
imprime com os dois zeros à esquerda, e nove dígitos soltos depois do
rótulo fariam de um protocolo um candidato. O valor fica no grupo `value`.
Entra por `IDENTIFIERS`.
"""

IDENTIFIERS: tuple[Check, ...] = (PIS, VOTER_ID, CNH, RENAVAM)
"""Os ids por escolha, para `entities=[*DEFAULT_ENTITIES, *IDENTIFIERS]`.

Como sinal, `EvidenceRouter([*DEFAULT_SIGNALS, *map(FailsCheck, IDENTIFIERS)])`.
"""


def _value_of(check: Check, match: re.Match[str]) -> tuple[int, int, str]:
    """O valor numa ocorrência da forma: o grupo `value`, quando a forma o nomeia, ou ela inteira.

    Um campo que só o rótulo distingue, como o registro da CNH, põe o rótulo
    na forma e o valor no grupo: a entidade sai só com o valor.
    """
    group = "value" if "value" in check.pattern.groupindex else 0
    return match.start(group), match.end(group), match.group(group)


def failures(check: Check, text: str) -> int:
    """Quantas ocorrências da forma impressa de `check` no texto falham a verificação.

    O texto passa antes por `fold_lookalikes`: um CPF com hífen tipográfico
    também é verificado.
    """
    folded = fold_lookalikes(text)
    return sum(
        1 for m in check.pattern.finditer(folded) if not check.is_valid(_value_of(check, m)[2])
    )


type Match = tuple[int, int, str, bool, list[Chunk]]
"""Uma ocorrência da forma de um campo: começo, fim, valor impresso, se confere, e as linhas."""


def _matches(
    check: Check, chunks: Sequence[Chunk], *, labeled: bool = True, text: str | None = None
) -> list[Match]:
    """Cada ocorrência da forma de `check` nas linhas unidas, com as linhas que ela toca.

    As linhas são unidas por quebra de linha e dobradas por `fold_lookalikes`,
    que não muda posição nenhuma; quem já as uniu passa o resultado em `text`.
    Um valor partido entre duas linhas, como `R$` no fim de uma e o número na
    seguinte, toca as duas. O valor sai com os espaços colapsados.
    """
    if text is None:
        text = fold_lookalikes(_text_of(chunks))

    def touched(begin: int, end: int) -> list[Chunk]:
        return touched_lines(chunks, begin, end)

    standard = list(check.pattern.finditer(text))
    found: list[Match] = []
    for match in standard:
        begin, end, value = _value_of(check, match)
        found.append(
            (begin, end, " ".join(value.split()), check.is_valid(value), touched(begin, end))
        )
    if labeled and check.labeled is not None:
        for match in check.labeled.finditer(text):
            begin, end = match.span("value")
            if any(m.start() <= begin < m.end() for m in standard):
                continue
            value = match.group("value")
            valid = check.is_valid("".join(value.split()))
            found.append((begin, end, " ".join(value.split()), valid, touched(begin, end)))
        found.sort(key=lambda m: m[0])
    return found


def entities_of(
    checks: Sequence[Check], page: Page, chunks: Sequence[Chunk], *, spans: bool = False
) -> list[Entity]:
    """Cada valor que uma das verificações casa na leitura da página, com estado e linha.

    Vale para toda linha, composta ou lida por um motor: o estado diz se o
    valor é possível, e quem lê o resultado combina com `RoutingDecision` e
    com `Chunk.source` para saber se um `failed` é do documento ou da
    leitura. A ordem é a do texto da página, como `chunks` veio. Com
    `spans`, cada valor diz onde está no texto das linhas dele (`Entity.span`).
    """
    begins: dict[str, int] = {}
    position = 0
    for chunk in chunks:
        begins.setdefault(chunk.id, position)
        position += len(chunk.text) + 1
    found: list[tuple[int, Entity]] = []
    text = fold_lookalikes(_text_of(chunks))
    for check in checks:
        for start, end, value, valid, lines in _matches(check, chunks, text=text):
            if valid:
                state = EntityState.CONFIRMED if check.proves(value) else EntityState.WELL_FORMED
            else:
                state = EntityState.FAILED
            entity = Entity(
                kind=check.name,
                value=value,
                state=state,
                page=page.index,
                bbox=BBox.envelope([c.bbox for c in lines]),
                chunk_ids=tuple(c.id for c in lines),
                span=(start - begins[lines[0].id], end - begins[lines[0].id]) if spans else None,
            )
            found.append((start, entity))
    # Estável: na mesma posição, fica a ordem das verificações.
    return [entity for _, entity in sorted(found, key=lambda t: t[0])]


_BROKEN_DECODE = re.compile("[\ufffd\ue000-\uf8ff\x00-\x08\x0b\x0c\x0e-\x1f]")


def garbled_runs(text: str) -> int:
    """Quantos caracteres o texto tem que só uma decodificação quebrada produz.

    Três formas, todas categóricas: o caractere de substituição U+FFFD, um
    ponto da área de uso privado, que é o que sai de uma fonte sem tabela
    ToUnicode, e um caractere de controle que não é quebra de linha nem
    tabulação. Nenhum texto impresso os contém.
    """
    return len(_BROKEN_DECODE.findall(text))


@runtime_checkable
class Signal(Protocol):
    """Um sinal sobre a leitura barata de uma página.

    Devolve quantas ocorrências encontrou: zero quer dizer "sem evidência", e
    mais ocorrências desempatam entre páginas do mesmo sinal. A prioridade entre
    sinais é a ordem em que a política os recebe, não um peso.
    """

    @property
    def name(self) -> str:
        """O nome com que a decisão cita o sinal."""
        ...

    def __call__(self, page: Page, chunks: Sequence[Chunk]) -> int:
        """Quantas ocorrências a página tem; zero quer dizer sem evidência."""
        ...


@runtime_checkable
class LineSignal(Signal, Protocol):
    """Um sinal que aponta a linha em que disparou.

    `FailsCheck` e `GarbledText` o implementam; `Document.doubts` lista o que
    eles apontam. `field` é o nome com que a dúvida cita o que falhou: o campo
    de uma verificação, ou o nome do sinal.
    """

    @property
    def field(self) -> str:
        """O nome com que a dúvida cita o que falhou."""
        ...

    def failing(self, page: Page, chunks: Sequence[Chunk]) -> list[tuple[str, Chunk]]:
        """Cada valor que falha, com cada linha em que ele está."""
        ...


def signal(name: str) -> Callable[[Callable[[Page, Sequence[Chunk]], int]], Signal]:
    """Transforma uma função `(page, chunks) -> int` num `Signal` com nome.

    É o caminho curto para inserir um critério próprio de escalada:

    ```python
    @signal("termo de classe")
    def class_term(page, chunks):
        text = " ".join(c.text for c in chunks).lower()
        return sum(term in text for term in ("quirografário", "trabalhista"))
    ```
    """

    def wrap(fn: Callable[[Page, Sequence[Chunk]], int]) -> Signal:
        return _FunctionSignal(name, fn)

    return wrap


class _FunctionSignal:
    def __init__(self, name: str, fn: Callable[[Page, Sequence[Chunk]], int]) -> None:
        self.name = name
        self._fn = fn

    def __call__(self, page: Page, chunks: Sequence[Chunk]) -> int:
        """Delega à função embrulhada."""
        return self._fn(page, chunks)


def _text_of(chunks: Sequence[Chunk]) -> str:
    return "\n".join(c.text for c in chunks)


def touched_lines(chunks: Sequence[Chunk], begin: int, end: int) -> list[Chunk]:
    """As linhas que o trecho `[begin, end)` do texto unido por `_text_of` toca."""
    out: list[Chunk] = []
    start = 0
    for chunk in chunks:
        if start < end and begin < start + len(chunk.text):
            out.append(chunk)
        start += len(chunk.text) + 1
    return out


def _machine_chunks(page: Page, chunks: Sequence[Chunk]) -> list[Chunk]:
    """Os chunks que um motor reconheceu, e não um tipógrafo compôs.

    Numa página `SEARCHABLE_SCAN` a camada de texto também é de um motor. Nas
    outras, a camada foi composta, e conta só o que outro leitor leu: o erro
    da camada composta é do documento, e reler devolveria o mesmo erro.
    """
    if page.substrate is Substrate.SEARCHABLE_SCAN:
        return list(chunks)
    return [c for c in chunks if c.source != TextLayerReader.name]


def _machine_text(page: Page, chunks: Sequence[Chunk]) -> str:
    """O texto dos chunks de `_machine_chunks`, uma linha por chunk."""
    return _text_of(_machine_chunks(page, chunks))


class EmptyRead:
    """A leitura barata não trouxe texto nenhum.

    Uma folha em branco também volta vazia, e é o falso positivo conhecido.
    """

    name = "leitura vazia"

    def __call__(self, page: Page, chunks: Sequence[Chunk]) -> int:
        """1 se não há texto, 0 se há."""
        del page
        return 0 if _text_of(chunks).strip() else 1


class FailsCheck:
    """Campo na forma impressa que falha a própria verificação.

    Só em texto escrito por máquina: numa página composta o erro é de quem
    digitou o documento, e reler devolveria o mesmo erro. Um documento que
    imprime um CPF errado, ou uma data errada quando a verificação é de data,
    também dispara, e reler devolve o mesmo valor: é o falso positivo
    conhecido.
    """

    def __init__(self, check: Check) -> None:
        """Fixa a verificação; o nome do sinal é o do campo."""
        self.check = check
        self.name = f"{check.name} que falha a verificação"
        self.field = check.name

    def __call__(self, page: Page, chunks: Sequence[Chunk]) -> int:
        """Quantas ocorrências falham; 0 em texto composto."""
        return failures(self.check, _machine_text(page, chunks))

    def failing(self, page: Page, chunks: Sequence[Chunk]) -> list[tuple[str, Chunk]]:
        """Cada valor que falha, com cada chunk em que ele está; vazio em texto composto.

        Procura no mesmo texto que o sinal conta, as linhas unidas por quebra
        de linha. Um valor partido entre duas linhas, como `R$` no fim de uma
        e o número na seguinte, aparece uma vez para cada linha que ele toca,
        e com os espaços colapsados: `R$ 4.000,0o`.
        """
        return [
            (value, chunk)
            for _, _, value, valid, lines in _matches(
                self.check, _machine_chunks(page, chunks), labeled=False
            )
            if not valid
            for chunk in lines
        ]

    def values(self, chunk: Chunk) -> list[tuple[str, bool]]:
        """Os valores do campo no chunk, com as letras parecidas dobradas, e se cada um confere."""
        return [
            (value, self.check.is_valid(value))
            for m in self.check.pattern.finditer(fold_lookalikes(chunk.text))
            for value in (_value_of(self.check, m)[2],)
        ]

    def valid_in(self, chunk: Chunk) -> bool:
        """Se o chunk traz ao menos um valor do campo e todos conferem."""
        values = self.values(chunk)
        return bool(values) and all(valid for _, valid in values)


class GarbledText:
    """Caracteres que só uma decodificação quebrada produz.

    É o sinal da camada de texto que existe, extrai sem erro e é lixo: uma
    fonte sem tabela ToUnicode numa página composta, ou um motor de OCR que
    gravou o que não sabia ler. Vale também em texto composto, porque reler os
    pixels conserta o que a decodificação quebrou.
    """

    name = "texto mal decodificado"
    field = name

    def __call__(self, page: Page, chunks: Sequence[Chunk]) -> int:
        """Quantos caracteres de decodificação quebrada a página tem."""
        del page
        return garbled_runs(_text_of(chunks))

    def failing(self, page: Page, chunks: Sequence[Chunk]) -> list[tuple[str, Chunk]]:
        """Cada linha com caractere de decodificação quebrada, com os pontos de código dela.

        O valor é a lista dos pontos de código, como `U+FFFD, U+F0B7`, para
        que quem revisa veja qual caractere a linha traz. É a evidência por
        linha do sinal, no mesmo formato de `FailsCheck.failing`.
        """
        del page
        out: list[tuple[str, Chunk]] = []
        for chunk in chunks:
            found = sorted({f"U+{ord(c):04X}" for c in _BROKEN_DECODE.findall(chunk.text)})
            if found:
                out.append((", ".join(found), chunk))
        return out


def mojibake_in(text: str) -> str | None:
    """Por que o texto parece decodificado com a codificação errada, ou None.

    Duas famílias. O texto gravado em UTF-8 e lido como Latin-1 ou
    Windows-1252 (`SÃƒO` por `SÃO`) é o que o ftfy reconhece. O texto em
    Latin-1 lido como Mac Roman (`honor·rios` por `honorários`) o ftfy não
    cobre: a linha é relida pelos dois codecs da biblioteca padrão, e um
    símbolo entre duas letras que vira letra na releitura é a evidência.
    Categórico, sem limiar; um símbolo solto, como o ponto mediano de uma
    lista, fica de fora porque não está entre letras. O traço, o apóstrofo
    e as aspas tipográficas ficam de fora porque vivem coladas a letras
    (`SAUDE-GERAL` com meia-risca, `D'Agua` com apóstrofo curvo, a alínea
    entre aspas sem espaço).
    """
    try:
        from ftfy.badness import is_bad
    except ModuleNotFoundError as exc:  # pragma: no cover - depende do ambiente
        raise ModuleNotFoundError(
            "o sinal MojibakeText precisa do extra: uv add 'docaudit[mojibake]'"
        ) from exc
    if is_bad(text):
        return "UTF-8 lido como Latin-1"
    try:
        other = text.encode("mac_roman").decode("latin-1")
    except UnicodeError:
        return None
    for i in range(1, len(text) - 1):
        a, b = text[i], other[i]
        if a == b or a.isalnum() or a.isspace() or not b.isalpha():
            continue
        if a == "'" or unicodedata.category(a) in _IN_WORD_PUNCTUATION:
            continue
        if text[i - 1].isalpha() and text[i + 1].isalpha():
            return "Latin-1 lido como Mac Roman"
    return None


_IN_WORD_PUNCTUATION = frozenset({"Pd", "Pi", "Pf"})
"""Traços e aspas de abertura e de fecho, que o uso cola a letras; o apóstrofo curvo é `Pf`."""


class MojibakeText:
    """Texto decodificado com a codificação errada: `honor·rios` por `honorários`.

    É a camada de texto cuja tabela ToUnicode está errada, que extrai sem
    erro e parece texto. `GarbledText` não a vê: nenhum caractere é de
    substituição ou de controle. Pede o extra `mojibake`; o que cada família
    prova está em `mojibake_in`. Fora de `DEFAULT_SIGNALS` até que uma
    medição em corpus público conte os falsos alarmes:
    `EvidenceRouter([*DEFAULT_SIGNALS, MojibakeText()])`. Com um OCR em
    `strong=`, a página vai aos pixels.
    """

    name = "texto com codificação trocada"
    field = name

    def __call__(self, page: Page, chunks: Sequence[Chunk]) -> int:
        """Quantas linhas da página parecem decodificadas com a codificação errada."""
        del page
        return sum(1 for c in chunks if mojibake_in(c.text) is not None)

    def failing(self, page: Page, chunks: Sequence[Chunk]) -> list[tuple[str, Chunk]]:
        """Cada linha suspeita, com a família de troca que a denuncia."""
        del page
        out: list[tuple[str, Chunk]] = []
        for chunk in chunks:
            reason = mojibake_in(chunk.text)
            if reason is not None:
                out.append((reason, chunk))
        return out


DEFAULT_SIGNALS: tuple[Signal, ...] = (
    EmptyRead(),
    GarbledText(),
    FailsCheck(CPF),
    FailsCheck(CNPJ),
    FailsCheck(CNJ),
    FailsCheck(AMOUNT_BRL),
    FailsCheck(AMOUNT_PRE_REAL),
)
"""Os sinais categóricos que já pegaram leitura errada, na ordem de prioridade.

Essa ordem não foi medida."""

DEFAULT_CHECKS: tuple[FailsCheck, ...] = tuple(
    s for s in DEFAULT_SIGNALS if isinstance(s, FailsCheck)
)
"""As verificações entre os sinais padrão: as que apontam a linha que falhou."""


@dataclass(frozen=True)
class StampFormat:
    r"""A tarja que um sistema de processo eletrônico imprime em cada página de uma peça.

    `pattern` casa a tarja inteira nas linhas da camada de texto, unidas por
    quebra de linha na ordem do arquivo, e nomeia o que ela traz: `code`, o
    id da peça, sempre; e, quando a tarja os imprime, `process`, `signer`,
    `date`, `time` e `protocol`. `date_format` e `time_format` leem a data e
    a hora, no formato de `datetime.strptime`. `tz`, um nome da base IANA
    como `America/Sao_Paulo`, dá fuso a `Stamp.at`; sem ele, a hora fica
    como impressa, sem fuso, porque a tarja não diz o tribunal.
    `process_check` confere o número do processo, o dígito do CNJ por
    omissão; a tarja que não passa não é tarja, como a de data que não
    existe. `process(stamps=)` recebe o formato ou o nome dele em
    `STAMP_FORMATS`:

    ```python
    MEU = StampFormat("meu-sistema", re.compile(r"Documento (?P<code>\d{12})"))
    docaudit.process("autos.pdf", stamps=["e-saj", "pje", MEU])
    ```
    """

    name: str
    pattern: re.Pattern[str]
    date_format: str = "%d/%m/%Y"
    time_format: str = "%H:%M"
    process_check: Check | None = CNJ
    tz: str | None = None

    def __post_init__(self) -> None:
        """Recusa o formato sem o grupo `code`, e o fuso que a base IANA não conhece."""
        if "code" not in self.pattern.groupindex:
            raise ValueError(f"a tarja {self.name!r} precisa do grupo `code`")
        if self.tz is not None:
            try:
                ZoneInfo(self.tz)
            except ZoneInfoNotFoundError as exc:
                raise ValueError(f"a tarja {self.name!r}: fuso desconhecido {self.tz!r}") from exc


_CNJ_PRINTED = r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}"
ESAJ_STAMP = StampFormat(
    "e-saj",
    re.compile(
        r"(?i)assinado\s+digitalmente\s+por\s+(?P<signer>[^,]{3,200}?)\s*,\s*"
        r"(?:protocolado|liberado\s+nos\s+autos)\s+em\s+(?P<date>\d{2}/\d{2}/\d{4})\s+[àa]s\s+"
        r"(?P<time>\d{2}:\d{2})(?:\s*,\s*sob\s+o\s+n[úu]mero\s+(?P<protocol>[0-9A-Za-z]+))?"
        r"\s*\.?\s*Para\s+conferir\s+o\s+original,\s*acesse\s+o\s+site\s+\S+?,?\s+"
        rf"informe\s+o\s+processo\s+(?P<process>{_CNJ_PRINTED})\s+e\s+c[óo]digo\s+"
        r"(?P<code>[0-9A-Za-z]{6,12})\b"
    ),
)
"""A tarja do e-SAJ inteira, nas suas duas formas: a peça protocolada e o ato liberado nos autos.

A tarja vertical chega em duas linhas, a da assinatura e a da conferência,
e a expressão casa sobre as linhas unidas por quebra de linha. A tarja com
dois signatários não tem o ponto antes de `Para conferir`.
"""


PJE_STAMP = StampFormat(
    "pje",
    re.compile(
        r"Assinado\s+eletronicamente\s+por:\s*(?P<signer>[^\n]+?)\s*-\s*"
        r"(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<time>\d{2}:\d{2})(?::\d{2})?"
        r"[^\n]*(?:\n[^\n]*){0,3}?\n?[^\n]*?N[úu]mero\s+do\s+documento:\s*(?P<code>\d{20,32})"
    ),
)
"""A assinatura do PJe e o número do documento que vem depois dela, até três linhas abaixo.

Ponto de partida: confira nos seus documentos.
"""

PROJUDI_PR_STAMP = StampFormat(
    "projudi-pr",
    re.compile(
        r"Identificador:\s*(?P<code>[A-Z0-9]{5}(?:\s[A-Z0-9]{5}){3})\s*"
        rf"PROJUDI\s+-\s+Processo:\s*(?P<process>{_CNJ_PRINTED})\s*-\s*Ref\.\s*mov\.\s*[\d.]+"
        r"(?:\s*-\s*Assinado\s+digitalmente\s+por\s+(?P<signer>[^\n]+))?"
    ),
)
"""A validação e o rodapé do Projudi do TJPR. Ponto de partida, como `PJE_STAMP`."""

PROJUDI_GO_STAMP = StampFormat(
    "projudi-go",
    re.compile(
        r"Assinado\s+e\s+Publicado\s+Digitalmente\s+em\s+(?P<date>\d{2}/\d{2}/\d{4})\s+"
        r"(?P<time>\d{2}:\d{2}:\d{2})\s+Assinado\s+por\s+(?P<signer>[^:\n]+)[^\n]*\s+"
        r"Localizar\s+pelo\s+c[óo]digo:\s*(?P<code>\d{20,30})"
    ),
    time_format="%H:%M:%S",
)
"""O rodapé do Projudi do TJGO. O nome para antes dos dois-pontos: o CPF que segue não entra.

Ponto de partida, como `PJE_STAMP`.
"""

EPROC_STAMP = StampFormat(
    "eproc",
    re.compile(
        rf"Processo\s+(?P<process>{_CNJ_PRINTED})/[A-Z]{{2}},\s+"
        r"(?P<code>Evento\s+\d+,\s+[A-Z_]+\d*),\s+P[áa]gina\s+\d+"
    ),
)
"""O rodapé do eproc: o processo, e o evento e o anexo como id da peça.

A `Página` dele é a do anexo, não a do processo, e não é folha.
Ponto de partida, como `PJE_STAMP`.
"""

STAMP_FORMATS: dict[str, StampFormat] = {
    f.name: f for f in (ESAJ_STAMP, PJE_STAMP, PROJUDI_PR_STAMP, PROJUDI_GO_STAMP, EPROC_STAMP)
}
"""Os formatos que `process(stamps=)` aceita pelo nome."""

DEFAULT_STAMPS: tuple[StampFormat, ...] = (ESAJ_STAMP,)
"""Os formatos de tarja procurados por omissão: o e-SAJ, de São Paulo e de outros tribunais."""

PROJUDI_PAGE = Check(
    "pagina-projudi",
    re.compile(r"(?<![^\W\d_])Página\s+(?P<number>[0-9]{1,3}(?:\.[0-9]{3})+|[0-9]+)\b(?!\s*de\b)"),
    lambda _: True,
)
"""A página do processo que o Projudi imprime no pé de cada folha, `Página 9.118`.

`Página 2 de 9` não casa: é a página do documento, não a do processo. No
eproc, a `Página` do rodapé é a do anexo, e esta forma não serve.
Ponto de partida, como `PJE_STAMP`.
"""

FOLHA_FORMATS: dict[str, Check] = {c.name: c for c in (FOLHA, PROJUDI_PAGE)}
"""As formas de folha que `process(folhas=)` aceita pelo nome."""


DEFAULT_ENTITIES: tuple[Check, ...] = (
    *(c.check for c in DEFAULT_CHECKS),
    DATE_DMY,
    DATE_WEEKDAY,
    DATE_VERBOSE,
    FOLHA,
    NFE_KEY,
    BOLETO,
    ARRECADACAO,
)
"""Os campos de `Result.entities` por omissão: as verificações padrão, datas, folha e códigos.

A chave de acesso, a linha digitável e o código de arrecadação extraem e
não encaminham: ficam fora de `DEFAULT_SIGNALS`. Para encaminhar por eles,
`EvidenceRouter([*DEFAULT_SIGNALS, FailsCheck(NFE_KEY)])`.
"""


class EvidenceRouter:
    """Encaminha só as páginas cuja leitura barata está provadamente errada ou vazia.

    Cada sinal diz quantas ocorrências encontrou numa página. A prioridade é a
    ordem da lista de sinais; dentro de um sinal, mais ocorrências primeiro;
    depois o índice da página. Não gasta orçamento em página sem sinal: um
    orçamento folgado sobra.

    `min_failures` é o mínimo de valores que falham, somados entre os
    `FailsCheck`, para a página ser encaminhada só por eles; os outros sinais
    encaminham com uma ocorrência. Não é calibrado: o padrão, 1, encaminha
    toda falha, e o porquê de outro valor está em `docs/concepts/policy.md`.
    Vale também com `reread="region"`, em que a página abaixo do mínimo
    deixa de reler o recorte barato das suas linhas.

    Para inserir um critério próprio, passe a lista: ver `signal`.
    """

    name = "evidence"
    needs_reads = True

    def __init__(
        self, signals: Sequence[Signal] = DEFAULT_SIGNALS, *, min_failures: int = 1
    ) -> None:
        """Recebe os sinais em ordem de prioridade e o mínimo de valores que falham."""
        if not signals:
            raise ValueError("a política evidence precisa de pelo menos um sinal")
        self.signals = tuple(signals)
        self.min_failures = min_failures
        self._check_names = frozenset(s.name for s in self.checks)

    @property
    def checks(self) -> tuple[FailsCheck, ...]:
        """As verificações entre os sinais, na ordem deles."""
        return tuple(s for s in self.signals if isinstance(s, FailsCheck))

    def _evidence(self, page: Page, chunks: Sequence[Chunk]) -> dict[str, int]:
        """Contagem de cada sinal que disparou na página, na ordem da lista."""
        return {sig.name: count for sig in self.signals if (count := sig(page, chunks))}

    def _escalates(self, evidence: Mapping[str, int]) -> bool:
        """Se a evidência basta: um sinal que não é verificação, ou falhas até o mínimo."""
        if not evidence.keys() <= self._check_names:
            return True
        return sum(evidence.values()) >= self.min_failures

    def rank(
        self, pages: Sequence[Page], reads: Mapping[int, Sequence[Chunk]]
    ) -> tuple[list[int], dict[int, dict[str, int]]]:
        """As páginas que escalam, da primeira à última, e o que disparou em cada."""
        found = {p.index: e for p in pages if (e := self._evidence(p, reads.get(p.index, ())))}
        order = {sig.name: rank for rank, sig in enumerate(self.signals)}

        def priority(index: int) -> tuple[int, int, int]:
            # O primeiro sinal da lista que disparou manda; dentro dele, mais
            # ocorrências primeiro; depois o índice da página.
            name, count = next(iter(found[index].items()))
            return order[name], -count, index

        enough = [index for index, e in found.items() if self._escalates(e)]
        return sorted(enough, key=priority), found

    def decide(
        self,
        pages: Sequence[Page],
        budget: Budget,
        reads: Mapping[int, Sequence[Chunk]] | None = None,
    ) -> Sequence[RoutingDecision]:
        """Escala as páginas com evidência, na ordem de prioridade, até o orçamento."""
        if reads is None:
            raise ValueError("a política evidence decide sobre a leitura barata; passe `reads`")
        ranked, found = self.rank(pages, reads)
        allowance = budget.page_allowance(len(pages))
        chosen = set(ranked if allowance is None else ranked[:allowance])
        escalating = set(ranked)
        decisions: list[RoutingDecision] = []
        for p in pages:
            signals = found.get(p.index, {})
            if signals and p.index not in escalating:
                reason = f"{sum(signals.values())} x valor que falha, abaixo de {self.min_failures}"
            elif signals:
                name, count = next(iter(signals.items()))
                reason = f"{count} x {name}"
            else:
                reason = "sem evidência de falha"
            decisions.append(
                RoutingDecision(
                    page=p.index,
                    tier=Tier.STRONG if p.index in chosen else Tier.CHEAP,
                    reason=reason,
                    signals=signals,
                )
            )
        return decisions


_BUILTIN: dict[str, type] = {
    "all_cheap": AllCheap,
    "all_strong": AllStrong,
    "evidence": EvidenceRouter,
}


def get_policy(name: str) -> type:
    """Resolve uma política embutida pelo nome."""
    try:
        return _BUILTIN[name]
    except KeyError:
        raise LookupError(
            f"política {name!r} desconhecida; disponíveis: {sorted(_BUILTIN)}"
        ) from None
