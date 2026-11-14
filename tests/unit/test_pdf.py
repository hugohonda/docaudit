"""Testes de leitura de PDF e classificação de substrato.

Os PDFs são construídos à mão, sem dependência extra, para que a suíte não
precise de fixtures binárias nem de rede.
"""

import pytest
from tests.support import make_pdf, make_scanned_pdf
from tests.support.fixtures import EMPTY_PAGE, TEXT_CENTRAL, TEXT_MARGIN

from docaudit.pdf import (
    PageView,
    doc_id_for,
    drawn_lines_of,
    is_image,
    load_pages,
    opened,
    pdf_of_image,
    render_of,
    text_lines_of,
)
from docaudit.types import BBox, Substrate


def test_doc_id_is_stable_and_content_addressed():
    a, b = make_pdf(TEXT_CENTRAL), make_pdf(EMPTY_PAGE)
    assert doc_id_for(a) == doc_id_for(a)
    assert doc_id_for(a) != doc_id_for(b)
    assert len(doc_id_for(a)) == 16


def test_text_alone_in_the_margin_is_typeset_text_and_leaves_nothing_unread():
    """Sem raster não há o que um OCR leia: a página é o texto que ela tem."""
    page = load_pages(make_pdf(TEXT_MARGIN))[0]
    assert page.substrate is Substrate.BORN_DIGITAL
    assert page.unread == ()


def test_dimensions_carry_pt_px_and_dpi():
    pages = load_pages(make_pdf(TEXT_CENTRAL), dpi=300)
    dims = pages[0].dimensions
    assert dims.width_pt == pytest.approx(595.0)
    assert dims.dpi == 300


@pytest.mark.parametrize("dpi", [201, 300])
def test_pixel_dimensions_match_the_actual_render(dpi):
    """O denominador que um backend usa para normalizar caixas tem de ser exato.

    `pages_of` arredondava e o pdfium tetos: as duas contas discordavam em um
    pixel a 300 dpi, que é a resolução da Res. CNJ 420/2021. Quem normalizasse
    por `page.dimensions`, como o exemplo do README manda, teria todas as
    caixas deslocadas; o backend embutido não, porque usa o tamanho da imagem.
    Duas fontes de verdade para o mesmo número.
    """
    import io

    from PIL import Image

    doc = make_pdf(TEXT_CENTRAL)
    dims = load_pages(doc, dpi=dpi)[0].dimensions
    with opened(doc) as pdf, Image.open(io.BytesIO(render_of(pdf, 0, dpi=dpi))) as img:
        assert (dims.width_px, dims.height_px) == img.size


def test_multiple_pages_keep_index_and_substrate():
    pages = load_pages(make_pdf(TEXT_CENTRAL, EMPTY_PAGE, TEXT_CENTRAL))
    assert [p.index for p in pages] == [0, 1, 2]
    assert [p.substrate for p in pages] == [
        Substrate.BORN_DIGITAL,
        Substrate.IMAGE_ONLY,
        Substrate.BORN_DIGITAL,
    ]


def test_render_produces_a_png():
    with opened(make_pdf(TEXT_CENTRAL)) as pdf:
        png = render_of(pdf, 0, dpi=72)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_view_keeps_one_render_per_colour_mode():
    """Numa cascata, o leitor que pede RGB não pode receber o cinza do anterior."""
    doc = make_pdf(TEXT_CENTRAL)
    with opened(doc) as pdf:
        view = PageView(pdf, load_pages(doc)[0], dpi=72)
        gray, rgb = view.image(grayscale=True), view.image(grayscale=False)
        assert gray != rgb
        assert view.image(grayscale=True) is gray, "guardado, não renderizado de novo"


# --- O substrato do meio ------------------------------------------------------


def test_raster_with_text_layer_is_searchable_scan():
    """O caso central: extrai texto limpo e mesmo assim não pode ser confiado."""
    pages = load_pages(make_scanned_pdf(["EDITAL DE CONVOCACAO", "METALURGICA ANDRADE LTDA"]))
    page = pages[0]
    assert page.substrate is Substrate.SEARCHABLE_SCAN
    assert page.substrate_evidence["chars"] > 0
    assert page.substrate_evidence["invisible_text"] > page.substrate_evidence["visible_text"]


def test_raster_without_text_layer_is_image_only():
    assert load_pages(make_scanned_pdf())[0].substrate is Substrate.IMAGE_ONLY


# --- DPI por página ------------------------------------------------------------


def test_a_page_renders_at_the_native_resolution_of_its_raster():
    """Renderizar acima do raster não cria pixels; abaixo, joga fora os que existem."""
    scan_150 = load_pages(make_scanned_pdf(pixels=(1240, 1754)))[0]
    assert scan_150.substrate_evidence["native_dpi"] == 150.0
    assert scan_150.dimensions.dpi == 150
    thumbnail = load_pages(make_scanned_pdf())[0]
    assert thumbnail.substrate_evidence["native_dpi"] == 15.0
    assert thumbnail.dimensions.dpi == 150, "piso: abaixo dele o reconhecedor perde linhas"
    typeset = load_pages(make_pdf(TEXT_CENTRAL))[0]
    assert "native_dpi" not in typeset.substrate_evidence
    assert typeset.dimensions.dpi == 200, "sem raster, o padrão"


def test_an_explicit_dpi_applies_to_every_page():
    pages = load_pages(make_scanned_pdf(pixels=(1240, 1754)), dpi=300)
    assert pages[0].dimensions.dpi == 300


def test_the_view_renders_at_the_page_dpi():
    doc = make_scanned_pdf(pixels=(1240, 1754))
    with opened(doc) as pdf:
        page = load_pages(doc)[0]
        import io

        from PIL import Image

        with Image.open(io.BytesIO(PageView(pdf, page).image())) as img:
            assert img.size == (page.dimensions.width_px, page.dimensions.height_px)
            assert img.size[0] == 1240


# --- Linhas do texto embutido ------------------------------------------------


def test_glyphs_placed_one_by_one_come_back_as_one_line():
    """Um gerador que posiciona cada letra isoladamente não pode virar uma letra por chunk."""
    glyphs = " ".join(f"{14 if i else 0} 0 Td ({ch}) Tj" for i, ch in enumerate("Banco"))
    doc = make_pdf(f"BT /F1 24 Tf 100 400 Td {glyphs} ET {TEXT_CENTRAL.replace('400', '300')}")
    with opened(doc) as pdf:
        lines = text_lines_of(pdf, 0)
    assert [t for _, t, _ in lines] == ["Banco", "EDITAL DE CITACAO - RELACAO"]
    banco, edital = (b for b, _, _ in lines)
    assert banco.y1 <= edital.y0, "a primeira linha fica acima da segunda"
    assert 0.0 < banco.area < 0.05


def test_the_text_layer_comes_back_composed_and_whole():
    """Cedilha combinante vira "ç"; letra fora do plano básico não se perde."""
    to_unicode = {"a": "a", "c": "c\u0327", "o": "o", "B": "\U0001d400"}
    doc = make_pdf("BT /F1 24 Tf 100 400 Td (Bacao) Tj ET", to_unicode=to_unicode)
    with opened(doc) as pdf:
        ((_, text, _),) = text_lines_of(pdf, 0)
    assert text == "\U0001d400a\u00e7ao"


def test_a_hyphen_at_a_line_break_between_letters_stays_and_is_marked():
    """O pdfium junta as duas linhas visuais e marca o hífen; ele volta impresso, com o índice."""
    doc = make_pdf("BT /F1 12 Tf 100 400 Td (Responsavel pela im-) Tj 0 -14 Td (plantacao) Tj ET")
    with opened(doc) as pdf:
        ((_, text, hyphens),) = text_lines_of(pdf, 0)
    assert text == "Responsavel pela im-plantacao"
    assert hyphens == (19,)
    assert text[19] == "-"


def test_a_hyphen_whose_rest_is_in_the_next_column_splits_the_line():
    """O resto da palavra no topo da coluna da direita é outra linha, cada uma com a caixa dela."""
    doc = make_pdf(
        "BT /F1 12 Tf 60 120 Td (o ato foi publica-) Tj ET "
        "BT /F1 12 Tf 320 700 Td (do com erro) Tj ET"
    )
    with opened(doc) as pdf:
        lines = text_lines_of(pdf, 0)
    assert [(text, hyphens) for _, text, hyphens in lines] == [
        ("o ato foi publica-", (17,)),
        ("do com erro", ()),
    ]
    left, right = (box for box, _, _ in lines)
    assert left.y0 > 0.8, "a primeira metade fica no pé da coluna da esquerda"
    assert right.y1 < 0.2, "a segunda, no topo da coluna da direita"
    assert left.x1 < right.x0


def test_a_hyphen_with_another_line_between_the_halves_splits_the_line():
    doc = make_pdf(
        "BT /F1 12 Tf 60 700 Td (o ato foi publica-) Tj ET "
        "BT /F1 12 Tf 60 500 Td (do com erro) Tj ET "
        "BT /F1 12 Tf 60 600 Td (outra linha qualquer) Tj ET"
    )
    with opened(doc) as pdf:
        texts = sorted(text for _, text, _ in text_lines_of(pdf, 0))
    assert texts == ["do com erro", "o ato foi publica-", "outra linha qualquer"]


def test_the_hyphen_index_survives_the_composition_of_the_text():
    """Um "ç" decomposto antes do hífen encurta o texto no NFC; o índice vale no texto que sai."""
    to_unicode = {"c": "c\u0327", "a": "a", "m": "m", "o": "o", "-": "-"}
    doc = make_pdf("BT /F1 12 Tf 100 400 Td (cacam-) Tj 0 -14 Td (ao) Tj ET", to_unicode=to_unicode)
    with opened(doc) as pdf:
        ((_, text, hyphens),) = text_lines_of(pdf, 0)
    assert text == "\u00e7a\u00e7am-ao"
    assert hyphens == (5,)
    assert text[5] == "-"


def test_a_hyphen_after_a_digit_is_not_a_line_break_mark():
    """O pdfium só marca o hífen entre letras: um número CNJ partido fica em duas linhas."""
    doc = make_pdf(
        "BT /F1 12 Tf 100 400 Td (Processo 1000123-) Tj 0 -14 Td (47.2024.8.26.0100) Tj ET"
    )
    with opened(doc) as pdf:
        lines = text_lines_of(pdf, 0)
    assert [t for _, t, _ in lines] == ["Processo 1000123-", "47.2024.8.26.0100"]
    assert all(h == () for _, _, h in lines)


def test_the_symbol_bullet_comes_back_as_a_bullet():
    """O marcador que o Word desenha com a fonte Symbol fica na área de uso privado."""
    doc = make_pdf("BT /F1 12 Tf 100 400 Td (x Maior) Tj ET", to_unicode={"x": "\uf0b7"})
    with opened(doc) as pdf:
        ((_, text, _),) = text_lines_of(pdf, 0)
    assert text == "\u2022 Maior"


def test_a_font_that_returns_glyph_numbers_is_not_a_reading_and_its_area_is_unread():
    """Sem mapa para Unicode, a fonte devolve o número do glifo: controles que nenhum texto tem."""
    doc = make_pdf(TEXT_CENTRAL, to_unicode={"E": "\x05"})
    with opened(doc) as pdf:
        assert text_lines_of(pdf, 0) == []
    page = load_pages(doc)[0]
    assert page.substrate is Substrate.BORN_DIGITAL
    assert page.substrate_evidence["unmapped_text"] == 1.0
    assert page.substrate_evidence["visible_text"] == 0.0
    (box,) = page.unread
    assert box.x0 == pytest.approx(100 / 595, abs=0.01), "onde a linha começa"


def test_pieces_drawn_out_of_order_come_back_in_the_order_of_the_row():
    """A planilha desenha `R$ 17,86` num objeto só, que cobre o número e o `R$` da célula vizinha.

    Os objetos se sobrepõem, e o pdfium os deixa na ordem do arquivo.
    """
    doc = make_pdf(
        "BT /F1 12 Tf 160 400 Td (23,81) Tj ET "
        "BT /F1 12 Tf 100 400 Td [(R$) -9000 (17,86)] TJ ET "
        "BT /F1 12 Tf 200 400 Td (R$) Tj ET"
    )
    with opened(doc) as pdf:
        texts = [line.text for line in text_lines_of(pdf, 0)]
    assert texts == ["R$ 23,81 R$ 17,86"]


def test_rotated_text_keeps_the_order_the_file_draws():
    """A tarja vertical é escrita de baixo para cima; reordenar pelo x a embaralharia."""
    doc = make_pdf("BT /F1 10 Tf 0 1 -1 0 560 100 Tm (Pagina 3 de 9) Tj ET")
    with opened(doc) as pdf:
        texts = [line.text for line in text_lines_of(pdf, 0)]
    assert texts == ["Pagina 3 de 9"]


def test_only_text_written_on_a_diagonal_is_slanted():
    """A tarja vertical e a linha de cabeça para baixo não são diagonais; a marca d'água é."""
    doc = make_pdf(
        "BT /F1 10 Tf 70 800 Td (Linha do corpo) Tj ET\n"
        "BT /F1 10 Tf 0 1 -1 0 560 100 Tm (Tarja de baixo para cima) Tj ET\n"
        "BT /F1 10 Tf 0 -1 1 0 30 700 Tm (Tarja de cima para baixo) Tj ET\n"
        "BT /F1 10 Tf -1 0 0 -1 400 300 Tm (De cabeca para baixo) Tj ET\n"
        "BT /F1 40 Tf 0.707 0.707 -0.707 0.707 100 300 Tm (COPIA) Tj ET\n"
        "BT /F1 10 Tf 0.99999 0.00436 -0.00436 0.99999 70 200 Tm (Um quarto de grau) Tj ET"
    )
    with opened(doc) as pdf:
        slanted = {d.line.text: d.slanted for d in drawn_lines_of(pdf, 0)}
    assert slanted == {
        "Linha do corpo": False,
        "Tarja de baixo para cima": False,
        "Tarja de cima para baixo": False,
        "De cabeca para baixo": False,
        "COPIA": True,
        "Um quarto de grau": True,
    }


# ── Imagens como documento ────────────────────────────────────────────────────


def _png(size=(300, 200), dpi=None, mode="L", frames=1, fmt="PNG") -> bytes:
    import io

    from PIL import Image

    images = [Image.new(mode, size, 128 + i * 20) for i in range(frames)]
    buf = io.BytesIO()
    kwargs = {"dpi": (dpi, dpi)} if dpi else {}
    if frames > 1:
        images[0].save(buf, format=fmt, save_all=True, append_images=images[1:], **kwargs)
    else:
        images[0].save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def test_an_image_is_a_one_page_image_only_document_at_its_declared_dpi():
    """A folha tem o tamanho que o DPI declarado dá aos pixels, e o raster é reencontrado."""
    pages = load_pages(_png((300, 200), dpi=100))
    assert len(pages) == 1
    assert pages[0].substrate is Substrate.IMAGE_ONLY
    assert pages[0].dimensions.width_pt == pytest.approx(216.0)
    assert pages[0].substrate_evidence["native_dpi"] == 100.0
    assert pages[0].dimensions.dpi == 150, "o DPI nativo entra preso ao piso"


def test_an_image_without_dpi_takes_the_default():
    assert load_pages(_png())[0].substrate_evidence["native_dpi"] == 200.0


def test_a_multi_frame_tiff_is_one_page_per_frame():
    pages = load_pages(_png(frames=3, fmt="TIFF", dpi=200))
    assert [p.index for p in pages] == [0, 1, 2]


def test_a_path_with_image_suffix_is_read_as_image(tmp_path):
    path = tmp_path / "pagina.png"
    path.write_bytes(_png(dpi=200))
    assert is_image(path)
    assert not is_image(tmp_path / "pagina.pdf")
    assert doc_id_for(path) == doc_id_for(path.read_bytes()), "o id é o da imagem, não do PDF"
    assert len(load_pages(path)) == 1


def test_a_jpeg_is_embedded_without_recompression():
    """Os bytes do JPEG ficam no PDF como estão: nada é recodificado."""
    jpeg = _png((64, 48), dpi=72, mode="RGB", fmt="JPEG")
    assert jpeg in pdf_of_image(jpeg)
    assert jpeg not in pdf_of_image(_png((64, 48), dpi=72, mode="RGB"))


def test_rendering_an_image_document_returns_its_pixels():
    import io

    from PIL import Image

    doc = _png((80, 60), dpi=72)
    with opened(doc) as pdf, Image.open(io.BytesIO(render_of(pdf, 0, dpi=72))) as img:
        assert img.size == (80, 60)
        lo, hi = img.convert("L").getextrema()
        assert (lo, hi) == (128, 128)


# ── Camadas escondidas e rasters que ninguém leu ──────────────────────────────


def test_visible_text_covered_by_a_later_image_is_a_hidden_layer():
    """Texto desenhado antes do raster que o cobre: ninguém o vê, e ele lê o raster."""
    lines = ["Esta edição encontra-se no site da prefeitura"] * 4
    page = load_pages(make_scanned_pdf(lines, render_mode=0, text_before_image=True))[0]
    assert page.substrate is Substrate.SEARCHABLE_SCAN
    assert page.substrate_evidence["covered_text"] == 4.0
    assert page.unread == (), "a camada coberta é a leitura do raster"


def test_text_inside_a_form_is_placed_where_the_form_draws_it():
    """O formulário leva o texto da origem dele ao topo da folha, sob a metade escaneada."""
    page = load_pages(
        make_scanned_pdf(
            ["Esta edição encontra-se no site da prefeitura"],
            render_mode=0,
            text_before_image=True,
            raster_box=(0.0, 0.5, 1.0, 1.0),
            text_in_form=True,
        )
    )[0]
    assert page.substrate_evidence["covered_text"] == 1.0
    assert page.unread == ()


def test_text_stamped_over_a_scan_does_not_read_it():
    """O rodapé do PJe por cima da digitalização é camada à vista; o corpo segue sem leitura."""
    page = load_pages(make_scanned_pdf(["Num. 41560374 - Pág. 2"], render_mode=0))[0]
    assert page.substrate is Substrate.BORN_DIGITAL
    assert page.substrate_evidence["covered_text"] == 0.0
    (box,) = page.unread
    assert box.area == pytest.approx(1.0)


def test_a_folio_number_under_the_scan_does_not_read_it_when_the_page_text_is_visible():
    """Uma linha coberta pela digitalização, numa página de texto à vista: carimbo, não camada."""
    page = load_pages(
        make_scanned_pdf(
            ["fls. 339"],
            render_mode=0,
            text_before_image=True,
            raster_box=(0.0, 0.1, 1.0, 1.0),
            text_lines_below=["Assinado eletronicamente por", "Num. 2226937 - Pág. 3"],
            text_y_below=40,
        )
    )[0]
    assert page.substrate is Substrate.BORN_DIGITAL
    assert page.substrate_evidence["covered_text"] == 1.0
    (box,) = page.unread
    assert box.y1 == pytest.approx(0.9)


def test_an_invisible_layer_reads_the_raster_it_lies_on():
    page = load_pages(make_scanned_pdf(["TERMO DE AUDIENCIA"]))[0]
    assert page.substrate is Substrate.SEARCHABLE_SCAN
    assert page.unread == ()


def test_a_figure_beside_typeset_text_is_the_only_unread_region():
    """A figura de uma página composta é lida como região; o texto dela, não."""
    body = [f"Linha de texto composto número {i}" for i in range(8)]
    page = load_pages(
        make_scanned_pdf(body, render_mode=0, raster_box=(0.1, 0.05, 0.9, 0.45), text_y=780)
    )[0]
    assert page.substrate is Substrate.BORN_DIGITAL
    (box,) = page.unread
    assert box.x0 == pytest.approx(0.1)
    assert box.y0 == pytest.approx(0.55)
    assert box.y1 == pytest.approx(0.95)


def test_unread_rasters_come_top_to_bottom_whatever_their_order_in_the_page_stream():
    """O raster de baixo é desenhado antes no fluxo, e mesmo assim vem depois em `unread`."""
    page = load_pages(
        make_scanned_pdf(
            ["texto entre as figuras"],
            render_mode=0,
            raster_box=(0.1, 0.7, 0.9, 0.9),
            text_y=400,
            extra_raster_boxes=[(0.1, 0.1, 0.9, 0.3)],
        )
    )[0]
    assert page.substrate is Substrate.BORN_DIGITAL
    assert [round(b.y0, 2) for b in page.unread] == [0.1, 0.7]


def test_tiles_that_touch_are_one_unread_raster():
    """A digitalização gravada em ladrilhos encostados é uma imagem só para o leitor de pixels."""
    page = load_pages(
        make_scanned_pdf(
            ["tarja na margem"],
            render_mode=0,
            raster_box=(0.1, 0.5, 0.9, 0.9),
            text_y=820,
            extra_raster_boxes=[(0.1, 0.1, 0.5, 0.5), (0.5, 0.1, 0.9, 0.5)],
        )
    )[0]
    assert page.substrate is Substrate.BORN_DIGITAL
    (box,) = page.unread
    assert (box.x0, box.y0, box.x1, box.y1) == pytest.approx((0.1, 0.1, 0.9, 0.9))


def test_a_hidden_line_across_two_tiles_reads_both():
    """A camada de OCR atravessa os ladrilhos: lida como folha, nenhum ladrilho fica sem leitura."""
    page = load_pages(
        make_scanned_pdf(
            ["uma linha longa da camada escondida que atravessa os dois ladrilhos da folha"],
            raster_box=(0.5, 0.05, 0.9, 0.95),
            text_y=420,
            extra_raster_boxes=[(0.1, 0.05, 0.5, 0.95)],
        )
    )[0]
    assert page.substrate is Substrate.SEARCHABLE_SCAN
    assert page.unread == ()


def test_rasters_with_a_gap_between_them_stay_apart():
    """Duas figuras separadas por qualquer vão são duas regiões, e não há limiar para o vão."""
    page = load_pages(
        make_scanned_pdf(
            ["tarja na margem"],
            render_mode=0,
            raster_box=(0.1, 0.51, 0.9, 0.9),
            text_y=820,
            extra_raster_boxes=[(0.1, 0.1, 0.9, 0.5)],
        )
    )[0]
    assert [round(b.y0, 2) for b in page.unread] == [0.1, 0.5]


def test_a_region_view_crops_the_page_and_maps_boxes_back():
    import io

    from PIL import Image

    doc = make_scanned_pdf(pixels=(1240, 1754))
    with opened(doc) as pdf:
        view = PageView(pdf, load_pages(doc)[0], dpi=72)
        region = view.region(BBox(x0=0.5, y0=0.25, x1=1.0, y1=0.75))
        with Image.open(io.BytesIO(view.image())) as page_img:
            expected = BBox(x0=0.5, y0=0.25, x1=1.0, y1=0.75).to_pixels(*page_img.size)
        with Image.open(io.BytesIO(region.image())) as img:
            assert img.size == (expected[2] - expected[0], expected[3] - expected[1])
        assert region.page.dimensions.width_px == img.size[0], "as dimensões são as do recorte"
        assert region.text_lines() == ()
        assert view.rendered, "o recorte vem da renderização da página"
        back = region.to_page(BBox(x0=0.0, y0=0.0, x1=0.5, y1=1.0))
        assert (back.x0, back.y0, back.x1, back.y1) == pytest.approx((0.5, 0.25, 0.75, 0.75))


@pytest.mark.parametrize(
    ("turn", "corner"),
    [(90, BBox(x0=0.0, y0=0.5, x1=0.5, y1=1.0)), (270, BBox(x0=0.5, y0=0.0, x1=1.0, y1=0.5))],
)
def test_a_turned_region_shows_the_crop_upright_and_its_boxes_return_to_the_image(turn, corner):
    """O canto do alto à esquerda vai para onde o giro anti-horário o leva, e a caixa volta."""
    from PIL import Image

    class Painted(PageView):
        def pixels(self, *, grayscale=True):
            image = Image.new("L", (400, 200), 255)
            image.paste(0, (0, 0, 200, 100))
            return image

    doc = make_scanned_pdf(pixels=(1240, 1754))
    with opened(doc) as pdf:
        region = Painted(pdf, load_pages(doc)[0], dpi=72).region(
            BBox(x0=0.0, y0=0.0, x1=1.0, y1=1.0), turn=turn
        )
        before = region.page.dimensions
        assert (before.width_pt, before.height_pt) == pytest.approx(
            (load_pages(doc)[0].dimensions.height_pt, load_pages(doc)[0].dimensions.width_pt)
        )
        upright = region.pixels()
        assert upright.size == (200, 400)
        assert (region.page.dimensions.width_px, region.page.dimensions.height_px) == (200, 400)
        at = (int((corner.x0 + corner.x1) / 2 * 200), int((corner.y0 + corner.y1) / 2 * 400))
        assert upright.getpixel(at) == 0
        back = region.to_page(corner)
        assert (back.x0, back.y0, back.x1, back.y1) == pytest.approx((0.0, 0.0, 0.5, 0.5))


def test_a_body_drawn_in_vector_outlines_beside_a_margin_strip_is_unread():
    """Glifos em contornos e a tarja como único texto: o corpo é desenho sem leitura."""
    glyphs = " ".join(
        f"{70 + 8 * i} 500 m {74 + 8 * i} 510 l {78 + 8 * i} 500 l f" for i in range(40)
    )
    strip = "BT /F1 6 Tf 570 100 Td (Este documento e copia do original) Tj ET"
    page = load_pages(make_pdf(f"{glyphs}\n{strip}"))[0]
    assert page.substrate is Substrate.BORN_DIGITAL
    (box,) = page.unread
    assert box.x0 == pytest.approx(70 / 595, abs=1e-3)
    assert box.y1 == pytest.approx((842 - 500) / 842, abs=1e-3)


def test_outline_glyphs_around_a_heading_of_text_stay_unread():
    """Um cabeçalho de texto no meio do desenho não lê o corpo desenhado em contornos com curva."""
    glyphs = " ".join(
        f"{70 + 6 * i} 500 m {71 + 6 * i} 512 {74 + 6 * i} 512 {75 + 6 * i} 500 c f"
        for i in range(80)
    )
    heading = "BT /F1 10 Tf 150 505 Td (TITULO) Tj ET"
    page = load_pages(make_pdf(f"{glyphs}\n{heading}"))[0]
    assert page.substrate is Substrate.BORN_DIGITAL
    (box,) = page.unread
    assert box.x0 == pytest.approx(70 / 595, abs=1e-3)
    straight = " ".join(
        f"{70 + 6 * i} 498 m {72 + 6 * i} 514 l {75 + 6 * i} 498 l f" for i in range(80)
    )
    assert load_pages(make_pdf(f"{straight}\n{heading}"))[0].unread == (), "a régua reta é lida"


def _rounded(x: float, y: float, w: float, h: float, r: float) -> str:
    """Um retângulo de cantos arredondados, preenchido."""
    k = r * 0.55
    right, top = x + w, y + h
    return (
        f"{x + r} {y} m {right - r} {y} l "
        f"{right - r + k} {y} {right} {y + r - k} {right} {y + r} c {right} {top - r} l "
        f"{right} {top - r + k} {right - r + k} {top} {right - r} {top} c {x + r} {top} l "
        f"{x + r - k} {top} {x} {top - r + k} {x} {top - r} c {x} {y + r} l "
        f"{x} {y + r - k} {x + r - k} {y} {x + r} {y} c h f"
    )


def test_rounded_cells_a_logo_and_bullets_beside_text_are_read():
    """O fundo arredondado toca o texto dele; o logotipo e os marcadores são poucos contornos."""
    cells = " ".join(_rounded(60, 700 - 30 * i, 470, 24, 6) for i in range(10))
    text = " ".join(f"BT /F1 10 Tf 70 {708 - 30 * i} Td (Linha {i}) Tj ET" for i in range(10))
    logo = " ".join(_rounded(60 + 9 * i, 780, 8, 8, 3) for i in range(20))
    bullets = " ".join(_rounded(500, 80 + 12 * i, 6, 6, 3) for i in range(10))
    page = load_pages(make_pdf(f"0.9 g {cells} 0 g {text} {logo} {bullets}"))[0]
    assert page.unread == ()


def test_table_rules_around_their_cell_text_are_read():
    """As linhas de uma tabela cercam o texto das células: nada fica sem leitura."""
    frame = "60 380 500 60 re S 60 410 m 560 410 l S"
    page = load_pages(make_pdf(f"{frame}\n{TEXT_CENTRAL}"))[0]
    assert page.substrate is Substrate.BORN_DIGITAL
    assert page.unread == ()


def test_line_boxes_follow_the_visible_box_origin_and_the_page_rotation():
    """A folha cuja origem não é (0, 0) e a folha exibida girada: a caixa cai na página exibida."""
    plain = make_pdf("BT /F1 24 Tf 50 800 Td (TOPO) Tj ET")
    shifted = make_pdf("BT /F1 24 Tf 150 900 Td (TOPO) Tj ET", mediabox="100 100 695 942")
    turned = make_pdf("BT /F1 24 Tf 50 800 Td (TOPO) Tj ET", rotate=90)
    with opened(plain) as doc:
        ((base, _, _),) = text_lines_of(doc, 0)
    with opened(shifted) as doc:
        ((moved, _, _),) = text_lines_of(doc, 0)
    with opened(turned) as doc:
        ((rotated, _, _),) = text_lines_of(doc, 0)
    assert base.y1 < 0.1, "perto do topo"
    assert base.x0 < 0.15, "perto da esquerda"
    assert (moved.x0, moved.y0, moved.x1, moved.y1) == pytest.approx(
        (base.x0, base.y0, base.x1, base.y1)
    )
    # Girada 90 graus no sentido horário, o canto superior esquerdo vai para o direito.
    assert rotated.x0 > 0.9
    assert rotated.y0 == pytest.approx(base.x0, abs=0.01)


@pytest.mark.parametrize("rotate", [180, 270])
def test_the_page_rotation_does_not_change_the_lines_or_their_order(rotate):
    """A mesma folha exibida girada: as mesmas linhas, na mesma ordem.

    A 90 graus as linhas saem na ordem inversa, e esse giro fica de fora.
    """
    body = "\n".join(
        f"BT /F1 10 Tf 70 {700 - 40 * i} Td (Linha {i} do corpo) Tj ET" for i in range(5)
    )
    with opened(make_pdf(body)) as doc:
        upright = [text for _, text, _ in text_lines_of(doc, 0)]
    with opened(make_pdf(body, rotate=rotate)) as doc:
        turned = [text for _, text, _ in text_lines_of(doc, 0)]
    assert upright == [f"Linha {i} do corpo" for i in range(5)]
    assert turned == upright


def test_unreadable_documents_raise_one_plain_error():
    """Arquivo que não é PDF e PDF sem página nenhuma saem como `DocumentError`."""
    from docaudit.types import DocumentError

    with pytest.raises(DocumentError, match="não é um PDF"):
        load_pages(b"isto nao e um pdf")
    with pytest.raises(DocumentError, match="não é um PDF"):
        load_pages(make_pdf())
