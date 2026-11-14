import re

import pytest
from tests.support.fixtures import make_page

from docaudit.policies import (
    AMOUNT_BRL,
    AMOUNT_IN_WORDS,
    AMOUNT_PRE_REAL,
    ARRECADACAO,
    BOLETO,
    CNJ,
    CNPJ,
    CPF,
    DEFAULT_ENTITIES,
    DEFAULT_SIGNALS,
    NFE_KEY,
    Check,
    FailsCheck,
    GarbledText,
    failures,
    fold_lookalikes,
    garbled_runs,
    get_policy,
    signal,
)
from docaudit.types import BBox, Budget, Chunk, Substrate, Tier


@pytest.fixture
def pages():
    return [make_page(i) for i in range(10)]


@pytest.fixture
def typeset():
    return [make_page(i, substrate=Substrate.BORN_DIGITAL) for i in range(3)]


def _read(
    page: int, text: str, confidence: float | None = None, source: str = "fake"
) -> list[Chunk]:
    bbox = BBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    return [
        Chunk(
            id=Chunk.make_id("test", bbox, source, text, page=page),
            page=page,
            bbox=bbox,
            text=text,
            source=source,
            confidence=confidence,
        )
    ]


def test_all_cheap_never_escalates(pages):
    decisions = get_policy("all_cheap")().decide(pages, Budget())
    assert all(d.tier is Tier.CHEAP for d in decisions)


def test_all_vlm_escalates_everything(pages):
    decisions = get_policy("all_strong")().decide(pages, Budget())
    assert all(d.tier is Tier.STRONG for d in decisions)


def test_check_digits_separate_misread_ids_from_good_ones():
    def failing(text):
        return sum(failures(c, text) for c in (CPF, CNPJ, CNJ))

    assert failing("CPF 529.982.247-25 e CNPJ 11.222.333/0001-81") == 0
    assert failing("CPF 529.982.247-26 e CNPJ 11.222.333/0001-82") == 2
    assert failing("protocolo 52998224726, sem pontuação de id") == 0
    assert failing("processo 9001087-60.2022.8.26.0390") == 0
    assert failing("processo 9001087-61.2022.8.26.0390") == 1, "um dígito trocado"
    assert failing("CNPJ 12.ABC.345/01DE-35") == 0, "o exemplo da Receita"
    assert failing("CNPJ 12.ABC.345/01DF-35") == 1, "uma letra trocada"
    assert failing("autos 9001087-61.2022.8.26.0390.") == 1, "no fim da frase"
    assert failing("autos 9001087-61.2022.8.26.0390- Recuperação") == 1, "hífen colado"
    assert failing("CPF 529.982.247\u201026") == 1, "hífen tipográfico"
    devanagari = "".join(chr(0x0966 + int(c)) if c.isdigit() else c for c in "529.982.247-25")
    assert failing(f"CPF {devanagari}") == 0, "dígito de outro sistema não casa a forma"
    assert (
        failing("CPF \uff15\uff12\uff19.\uff19\uff18\uff12.\uff12\uff14\uff17\uff0d\uff12\uff16")
        == 1
    ), "largura total"


def test_a_value_glued_to_its_label_is_read_and_one_inside_a_number_is_not():
    def failing(text):
        return sum(failures(c, text) for c in (CPF, CNPJ, CNJ))

    assert failing("CPF n°/529.982.247-26") == 1, "barra depois do rótulo"
    assert failing("CNPJ n°.11.222.333/0001-82") == 1, "ponto depois do rótulo"
    assert failing("processo nº.9001087-61.2022.8.26.0390") == 1
    assert failing("1.529.982.247-26 e 7/529.982.247-26") == 0, "pedaço de número maior"
    assert failing("l.529.982.247-26") == 0, "a letra no lugar de um dígito ainda é número"
    assert failing("529.982.247-2611/12/1972") == 1, "a data da coluna seguinte colada"
    assert failing("529.982.247-26111") == 0, "dígitos colados sem barra são número maior"
    assert failing("529.982.247-2611/1") == 0, "barra que não começa uma data"
    assert failing("CPF 529,982.247-26") == 1, "vírgula no lugar de ponto"
    assert failures(CNPJ, "CNPJ 11,222.333/0001-82") == 1, "vírgula no lugar de ponto"
    assert failures(CNPJ, "CNPJ 11,222.333/0001-81") == 0
    assert failures(CNJ, "processo 9001087-61,2022.8.26.0390") == 1, "vírgula no lugar de ponto"
    assert failures(CNJ, "processo 9001087-60.2022,8.26.0390") == 0
    assert failures(CNPJ, "11.222.333/0001-8211/12/1972") == 1, "a data da coluna seguinte colada"
    assert failures(CNJ, "9001087-61.2022.8.26.039011/12/1972") == 1, (
        "a data da coluna seguinte colada"
    )
    assert failures(AMOUNT_BRL, "Totais 100,00% R$   4.00o,0o") == 1, "vão de coluna"
    assert failures(AMOUNT_BRL, "R$\n\n4.00o,0o") == 0, "duas quebras separam o valor do R$"


def test_folding_keeps_every_position_of_the_original():
    original = "nº 529.982.247\u201025, R$\u00a01.200,00 e \uff15 m²"
    folded = fold_lookalikes(original)
    assert len(folded) == len(original)
    assert folded == "nº 529.982.247-25, R$ 1.200,00 e 5 m²"


def test_a_check_of_the_user_works_like_the_builtin_ones(pages):
    even = Check("matrícula", re.compile(r"\bM-\d{5}\b"), lambda printed: int(printed[2:]) % 2 == 0)

    assert failures(even, "M-12344 e M-12345") == 1
    signal_ = FailsCheck(even)
    assert signal_.name == "matrícula que falha a verificação"
    assert signal_(pages[0], _read(0, "M-12345")) == 1


def test_amounts_the_brazilian_grafia_does_not_allow():
    assert failures(AMOUNT_BRL, "R$ 5.837,52 e R$ 1.200,00") == 0
    assert failures(AMOUNT_BRL, "R$ 5,837,52 e R$ 741 732,15") == 2
    assert failures(AMOUNT_BRL, "R$ 1.000.000,00. Pago R$ 1500,00") == 0
    assert failures(AMOUNT_BRL, "Item 3 150,00 e 1 500,00") == 0, "células vizinhas, sem R$"
    assert failures(AMOUNT_BRL, "R$741 732,15 e 10:000,00") == 2
    assert failures(AMOUNT_BRL, "R$ 4.00o,0o e R$ 1,0o") == 2, "letra no lugar de dígito"
    assert failures(AMOUNT_BRL, "R$ 1.00,00 e R$ 1.2345,00") == 2, "grupo sem três dígitos"
    assert failures(AMOUNT_BRL, "4.329.30 e R$ 15.062.39") == 2, "ponto no lugar da vírgula decimal"
    assert failures(AMOUNT_BRL, "R$ 18.77 e R$18.77") == 2, "ponto decimal logo depois do R$"
    assert failures(AMOUNT_BRL, "0.00\n  1.234.56 \nnota 7.5") == 2, "valor sozinho na linha"
    assert failures(AMOUNT_BRL, "versão 2.10 de 12.03 e art. 5.12 da lei") == 0
    assert AMOUNT_BRL.alike is not None
    assert AMOUNT_BRL.alike("R$ 18.77")
    assert AMOUNT_BRL.alike("4.329.30")
    assert not AMOUNT_BRL.alike("R$ 1.O00,00")
    assert not AMOUNT_BRL.alike("5,837,52")
    assert failures(AMOUNT_BRL, "art. 1.015, IV; 12.03.2024; 1.234.567") == 0
    assert failures(AMOUNT_BRL, "R$ mil") == 0


def test_an_amount_with_a_debit_or_credit_suffix_is_an_amount_without_the_real_sign():
    ledger = "SALDO ANTERIOR 1.249,01 C\nPIX ENVIADO 2.300,00 D\nTARIFA 12,50 Cada\nJUROS 0,5o C"
    matched = [m.group(0) for m in AMOUNT_BRL.pattern.finditer(ledger)]
    assert matched == ["1.249,01 C", "2.300,00 D", "0,5o C"], "`Cada` não é lançamento"
    assert failures(AMOUNT_BRL, ledger) == 1, "a letra no lugar do dígito falha"
    assert failures(AMOUNT_BRL, "1.249,01C e 1.249,01 c e 1.249,01") == 0, (
        "sem o sufixo não é valor"
    )
    assert [m.group(0) for m in AMOUNT_BRL.pattern.finditer("R$ 1.249,01 C")] == ["R$ 1.249,01"]


_NFE_KEY = "35240311222333000181550010000123451123456789"
_BOLETO = "23793.38128 60007.827136 95000.063305 4 84660000002603"
_ARRECADACAO_MOD10 = "81670000001-0 23456789999-7 99999999999-1 99999999999-1"
_ARRECADACAO_MOD11 = "81880000005-0 00000012222-0 22222222222-4 22222222222-4"


def test_the_access_key_checks_its_digit_and_its_closed_fields():
    spaced = " ".join(_NFE_KEY[i : i + 4] for i in range(0, 44, 4))
    assert failures(NFE_KEY, f"CHAVE DE ACESSO {spaced}. chNFe={_NFE_KEY}&x") == 0
    assert [m.group(0) for m in NFE_KEY.pattern.finditer(f"Id: {_NFE_KEY} e {_NFE_KEY}0")] == [
        _NFE_KEY
    ], "45 dígitos não são chave"
    assert failures(NFE_KEY, _NFE_KEY[:-1] + "X") == 1, "letra no lugar do dígito"
    assert failures(NFE_KEY, _NFE_KEY[:-1] + str((int(_NFE_KEY[-1]) + 1) % 10)) == 1, (
        "dígito trocado"
    )
    assert not NFE_KEY.is_valid("36" + _NFE_KEY[2:]), (
        "a UF 36 não existe, mesmo com o dígito refeito"
    )
    assert not NFE_KEY.is_valid(_NFE_KEY[:4] + "13" + _NFE_KEY[6:]), "o mês 13 não existe"
    assert not NFE_KEY.is_valid(_NFE_KEY[:20] + "01" + _NFE_KEY[22:]), "o modelo 01 não tem chave"


def test_the_boleto_line_checks_its_four_digits_in_print_and_glued():
    glued = _BOLETO.replace(".", "").replace(" ", "")
    assert failures(BOLETO, f"Pague até o vencimento: {_BOLETO}. Ou {glued}") == 0
    assert len(list(BOLETO.pattern.finditer(f"{_BOLETO} e {glued}"))) == 2
    assert failures(BOLETO, _BOLETO.replace("23793", "23798", 1)) == 1, (
        "o dígito do primeiro campo cai"
    )
    assert failures(BOLETO, _BOLETO.replace(" 4 ", " 5 ")) == 1, "o dígito geral cai"
    assert failures(BOLETO, _BOLETO.replace("0", "O", 1)) == 1, "letra no lugar do dígito"
    assert failures(BOLETO, glued[:-1]) == 0, "46 dígitos não são linha digitável"


def test_the_collection_code_checks_each_block_by_the_modulus_its_third_digit_names():
    assert failures(ARRECADACAO, f"{_ARRECADACAO_MOD10}\n{_ARRECADACAO_MOD11}") == 0
    spaced = _ARRECADACAO_MOD11.replace("-", " ")
    glued = _ARRECADACAO_MOD10.replace("-", "").replace(" ", "")
    assert failures(ARRECADACAO, f"{spaced} e {glued}") == 0
    assert failures(ARRECADACAO, _ARRECADACAO_MOD10.replace("8167", "8187", 1)) == 1, (
        "módulo 11 no código de módulo 10"
    )
    assert failures(ARRECADACAO, _ARRECADACAO_MOD10.replace("-0", "-1", 1)) == 1, (
        "o dígito do bloco cai"
    )
    assert failures(ARRECADACAO, _ARRECADACAO_MOD10.replace("0", "O", 1)) == 1, (
        "letra no lugar do dígito"
    )
    assert not ARRECADACAO.is_valid("7" + _ARRECADACAO_MOD10[1:]), "o produto é sempre 8"


def test_the_codes_extract_by_default_and_do_not_route():
    assert {NFE_KEY, BOLETO, ARRECADACAO} <= set(DEFAULT_ENTITIES)
    assert not any(
        isinstance(s, FailsCheck) and s.check in (NFE_KEY, BOLETO, ARRECADACAO)
        for s in DEFAULT_SIGNALS
    )


def test_amounts_in_the_currencies_before_the_real():
    assert failures(AMOUNT_PRE_REAL, "Cr$ 1.500.000 e NCz$ 925,23 e Cz$ 7.612.338,56") == 0
    assert failures(AMOUNT_PRE_REAL, "CR$ 1.500,00 e NCr$763.793,75") == 0
    assert failures(AMOUNT_PRE_REAL, "Cr$ 1.5o0,00 e Cz$ 1.00,00") == 2
    assert failures(AMOUNT_PRE_REAL, "R$ 1.5o0,00") == 0, "o real é de AMOUNT_BRL"
    assert failures(AMOUNT_PRE_REAL, "pagou Cr$ 1.000. Depois, Cr$ 2.000,00.") == 0, "ponto final"
    assert failures(AMOUNT_PRE_REAL, "pagou Cr$ 1.0O0.") == 1


def test_the_cruzeiro_real_is_not_read_as_the_real():
    assert failures(AMOUNT_BRL, "CR$ 1.5o0,00") == 0
    assert failures(AMOUNT_PRE_REAL, "CR$ 1.5o0,00") == 1


def test_evidence_escalates_only_pages_with_proof(pages):
    reads = {p.index: _read(p.index, "texto limpo, R$ 1.200,00") for p in pages}
    reads[2] = _read(2, "CPF 529.982.247-26")
    reads[5] = _read(5, "R$ 5,837,52")
    reads[7] = _read(7, "   ")
    decisions = get_policy("evidence")().decide(pages, Budget(), reads)
    escalated = {d.page: d.reason for d in decisions if d.tier is Tier.STRONG}
    assert set(escalated) == {2, 5, 7}, "sem evidência, nenhum gasto"
    assert escalated[2] == "1 x CPF que falha a verificação"
    assert escalated[7] == "1 x leitura vazia"
    by_page = {d.page: d.signals for d in decisions}
    assert by_page[2] == {"CPF que falha a verificação": 1}, "o canal estruturado"
    assert by_page[0] == {}, "sem sinal, mapa vazio"


def test_evidence_escalates_on_checks_only_from_the_minimum(pages):
    """Um valor errado fica apontado e barato; a leitura vazia escala sempre."""
    reads = {p.index: _read(p.index, "texto limpo") for p in pages}
    reads[1] = _read(1, "CPF 529.982.247-26")
    reads[2] = _read(2, "CPF 529.982.247-26 e R$ 5,837,52 e R$ 1.00,00")
    reads[3] = _read(3, "")
    decisions = get_policy("evidence")(min_failures=3).decide(pages, Budget(), reads)
    assert sorted(d.page for d in decisions if d.tier is Tier.STRONG) == [2, 3]
    assert decisions[1].reason == "1 x valor que falha, abaixo de 3"
    assert decisions[1].signals == {"CPF que falha a verificação": 1}, "o valor segue apontado"


def test_evidence_spends_a_tight_budget_by_priority(pages):
    reads = {p.index: _read(p.index, "texto limpo") for p in pages}
    reads[1] = _read(1, "R$ 5,837,52")
    reads[3] = _read(3, "CPF 529.982.247-26")
    reads[8] = _read(8, "")
    decisions = get_policy("evidence")().decide(pages, Budget(max_strong_pages=2), reads)
    assert sorted(d.page for d in decisions if d.tier is Tier.STRONG) == [3, 8]


def test_a_custom_signal_is_one_function_and_its_place_in_the_list_is_its_priority(pages):
    """O ponto de inserção: uma função com nome, e a ordem da lista decide."""

    @signal("termo de classe")
    def class_term(page, chunks):
        del page
        text = " ".join(c.text for c in chunks).lower()
        return text.count("quirografário")

    reads = {p.index: _read(p.index, "texto limpo") for p in pages}
    reads[4] = _read(4, "quirografário quirografário")
    reads[6] = _read(6, "quirografário")
    reads[8] = _read(8, "CPF 529.982.247-26")
    policy = get_policy("evidence")([class_term, *DEFAULT_SIGNALS])
    decisions = policy.decide(pages, Budget(max_strong_pages=2), reads)
    assert [d.page for d in decisions if d.tier is Tier.STRONG] == [4, 6], (
        "mais ocorrências primeiro"
    )
    assert decisions[4].reason == "2 x termo de classe"
    assert decisions[8].signals == {"CPF que falha a verificação": 1}


def test_a_typo_in_typeset_text_is_not_a_misread(typeset):
    """Reler uma página composta devolve o mesmo id quebrado: não vale o gasto."""
    reads = {
        p.index: _read(p.index, "CPF 529.982.247-26 e R$ 5,837,52", source="text_layer")
        for p in typeset
    }
    decisions = get_policy("evidence")().decide(typeset, Budget(), reads)
    assert all(d.tier is Tier.CHEAP for d in decisions)


def test_evidence_without_reads_says_what_it_needs(pages):
    with pytest.raises(ValueError, match="reads"):
        get_policy("evidence")().decide(pages, Budget())


def test_unknown_policy_lists_the_known_ones():
    with pytest.raises(LookupError, match="all_cheap"):
        get_policy("nao-existe")


def test_garbled_runs_count_only_characters_a_broken_decode_produces():
    assert garbled_runs("transtorno abstrato Schmidt CNPJ SRS xxxxxxx") == 0
    assert garbled_runs("texto mal decodificado \ufffd\ufffd") == 2
    assert garbled_runs("fonte sem ToUnicode \ue001\ue002 e controle \x07") == 3
    assert garbled_runs("quebra\nde linha\te tabulação") == 0


def test_garbled_text_counts_in_typeset_text_too():
    """Reler os pixels conserta uma fonte sem ToUnicode, e por isso o sinal é padrão."""
    typeset = make_page(0, substrate=Substrate.BORN_DIGITAL)
    assert GarbledText()(typeset, _read(0, "\ue001\ue002")) == 2
    assert any(isinstance(s, GarbledText) for s in DEFAULT_SIGNALS)


def test_ids_read_by_ocr_on_a_typeset_page_count_and_the_text_layer_does_not():
    """Numa página composta, o id quebrado da camada é erro do documento; o do OCR, de leitura."""
    typeset = make_page(0, substrate=Substrate.BORN_DIGITAL)
    bbox = BBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    layer = Chunk(id="a", page=0, bbox=bbox, text="CPF 529.982.247-26", source="text_layer")
    ocr = Chunk(id="b", page=0, bbox=bbox, text="CPF 529.982.247-26", source="ppocr")
    signal_ = FailsCheck(CPF)
    assert signal_(typeset, [layer]) == 0
    assert signal_(typeset, [layer, ocr]) == 1


def test_a_value_split_between_two_lines_points_to_both():
    """`R$` no fim de uma linha e o número na seguinte: o sinal conta, e a linha é apontada."""
    page = make_page(0, substrate=Substrate.IMAGE_ONLY)
    boxes = [BBox(x0=0.1, y0=y, x1=0.9, y1=y + 0.02) for y in (0.10, 0.13, 0.16)]
    texts = ["o pagamento mensal de R$", "4.000,0o (quatro mil reais)", "fim"]
    chunks = [
        Chunk(id=str(i), page=0, bbox=b, text=t, source="ocr")
        for i, (b, t) in enumerate(zip(boxes, texts, strict=True))
    ]
    check = FailsCheck(AMOUNT_BRL)
    assert check(page, chunks) == 1
    assert [(value, c.id) for value, c in check.failing(page, chunks)] == [
        ("R$ 4.000,0o", "0"),
        ("R$ 4.000,0o", "1"),
    ]


@pytest.mark.parametrize(
    ("chk", "read"),
    [
        (CPF, "CPF 529.982.247-2S"),
        (CPF, "CPF 529.9B2.247-25"),
        (CNPJ, "CNPJ l1.222.333/0001-81"),
        (CNPJ, "CNPJ 11.222.333/000I-81"),
        (CNPJ, "CNPJ 12.abc.345/01DE-35"),
        (CNJ, "processo 9001087-6O.2022.8.26.0390"),
    ],
)
def test_a_digit_read_as_a_lookalike_letter_is_caught_and_not_lost(chk, read):
    """Letra parecida no lugar do dígito: a forma casa, e a regra recusa."""
    assert failures(chk, read) == 1


def test_a_shape_without_any_digit_is_not_an_id():
    assert failures(CPF, "ver abc.def.ghi-jk") == 0
    assert [m.group(0) for m in CPF.pattern.finditer("abc.def.ghi-jk")] == []


@pytest.mark.parametrize(
    "printed",
    [
        "R$ 214.000,00 (duzentos e quatorze mil reais)",
        "R$ 214.000,00 (duzentos e catorze mil reais)",
        "R$ 1.514.712,67 (hum milhão, quinhentos e quatorze mil, setecentos e doze reais e "
        "sessenta e sete centavos)",
        "R$ 1.481.130,35 (um milhão, quatrocentos e oitenta e\num mil, cento e trinta reais e "
        "trinta e cinco centavos)",
        "R$ 1.200,00 (um mil e duzentos reais)",
        "R$ 1.000.000,00 (um milhão de reais)",
        "R$ 0,50 (cinquenta centavos)",
        "R$ 13.715.000,00 (treze milhões, setecen-\ntos e quinze mil reais)",
    ],
)
def test_an_amount_and_the_same_amount_in_words_agree(printed):
    assert failures(AMOUNT_IN_WORDS, printed) == 0
    assert [m.group(0) for m in AMOUNT_IN_WORDS.pattern.finditer(printed)] == [printed]


def test_an_amount_that_disagrees_with_its_words_fails():
    assert failures(AMOUNT_IN_WORDS, "R$ 4.400,00 (quatrocentos reais)") == 1
    assert (
        failures(AMOUNT_IN_WORDS, "R$ 2.918.058,36 (dois milhões, novecentos e dezoito reais)") == 1
    )


def test_without_a_number_in_words_or_a_well_formed_figure_there_is_no_evidence():
    """O parêntese que não é valor por extenso, e o número mal escrito, ficam com outros."""
    assert (
        failures(AMOUNT_IN_WORDS, "R$ 139.699.126,00 (sem os acréscimos dos encargos, em reais)")
        == 0
    )
    assert failures(AMOUNT_IN_WORDS, "R$ 4.000,0o (quatro mil reais)") == 0
    assert failures(AMOUNT_BRL, "R$ 4.000,0o (quatro mil reais)") == 1


def test_amount_in_words_is_not_a_default_signal():
    assert all(getattr(s, "check", None) is not AMOUNT_IN_WORDS for s in DEFAULT_SIGNALS)


@pytest.mark.parametrize(
    "words",
    [
        "vinte trinta",
        "dez dez",
        "mil mil",
        "cem e cem",
        "cem e cinco",
        "vinte e doze",
        "cinco vinte",
        "mil milhões",
        "doze e cinco",
    ],
)
def test_words_out_of_the_order_portuguese_writes_are_not_a_number(words):
    """Fora da ordem centena, dezena, unidade, ou com escalas que não descem: sem evidência."""
    assert failures(AMOUNT_IN_WORDS, f"R$ 50,00 ({words} reais)") == 0
    assert AMOUNT_IN_WORDS.is_valid(f"R$ 50,00 ({words} reais)")


def test_a_misread_word_that_still_forms_a_number_is_caught():
    assert failures(AMOUNT_IN_WORDS, "R$ 50,00 (cinco reais)") == 1
    assert failures(AMOUNT_IN_WORDS, "R$ 112,00 (cento e doze reais)") == 0


class TestMojibake:
    """O texto decodificado com a codificação errada, nas duas famílias que o sinal vê."""

    def test_latin1_read_as_mac_roman_is_caught_inside_a_word(self):
        from docaudit.policies import mojibake_in

        pytest.importorskip("ftfy", reason="precisa do extra `mojibake`")
        assert mojibake_in("honor·rios advocatÌcios") == "Latin-1 lido como Mac Roman"

    def test_utf8_read_as_latin1_is_caught_by_ftfy(self):
        from docaudit.policies import mojibake_in

        pytest.importorskip("ftfy", reason="precisa do extra `mojibake`")
        assert mojibake_in("SÃƒO PAULO, DECIS√ÉO") == "UTF-8 lido como Latin-1"

    @pytest.mark.parametrize(
        "text",
        [
            "honorários advocatícios",
            "SÃO PAULO",
            "R$ 4.000,00 (quatro mil reais)",
            "Fls. 16 — Autos nº 0001234-56.2020.8.26.0100",
            "E-mail: a@b.c · tel. (11) 1234",
            "“aspas” e ‘outras’, § 1º – art. 5°, inciso II",  # noqa: RUF001 - a tipografia é o teste
            "Ação de Execução – 2ª Vara, d'água, guarda-chuva",  # noqa: RUF001
            "Caixa D’Água, SAÚDE–GERAL, EPI’S, Cotriguaçu–MT, alínea“a”",  # noqa: RUF001
        ],
    )
    def test_legitimate_portuguese_is_not_flagged(self, text):
        from docaudit.policies import mojibake_in

        pytest.importorskip("ftfy", reason="precisa do extra `mojibake`")
        assert mojibake_in(text) is None

    def test_the_signal_routes_the_page_and_names_the_line(self):
        from tests.support import make_pdf

        from docaudit import process
        from docaudit.policies import DEFAULT_SIGNALS, EvidenceRouter, MojibakeText

        pytest.importorskip("ftfy", reason="precisa do extra `mojibake`")
        doc = make_pdf(
            "BT /F1 12 Tf 60 700 Td (Condeno ao pagamento de honor\\267rios advocat\\315cios) Tj ET"
        )
        policy = EvidenceRouter([*DEFAULT_SIGNALS, MojibakeText()])
        result = process(doc, policy=policy, cheap=["text_layer"])
        (decision,) = result.decisions
        assert decision.tier is Tier.STRONG
        assert decision.signals.get(MojibakeText.name) == 1
