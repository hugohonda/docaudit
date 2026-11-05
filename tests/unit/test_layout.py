"""O pós-processamento do detector de layout, sobre saídas sintéticas do grafo."""

import pytest

from docaudit.backends.layout import LABELS, regions_from

np = pytest.importorskip("numpy", reason="precisa do extra `layout`")

TEXT, TABLE, HEADER = LABELS.index("text"), LABELS.index("table"), LABELS.index("header")


def _outputs(queries: list[tuple[int, float, tuple[float, float, float, float]]]):
    """Consultas como (classe, pontuação, caixa cx cy w h); as demais ficam abaixo do limiar."""
    n = 8
    logits = np.full((n, len(LABELS)), -10.0)
    boxes = np.zeros((n, 4))
    for q, (label, score, box) in enumerate(queries):
        logits[q, label] = np.log(score / (1 - score))
        boxes[q] = box
    # Precedência: a consulta i vem antes de j quando i < j, com margem larga.
    order = np.full((n, n), -10.0)
    for i in range(n):
        for j in range(i + 1, n):
            order[i, j] = 10.0
    return logits, boxes, order


def test_regions_come_in_reading_order_with_corner_boxes():
    logits, boxes, order = _outputs(
        [
            (TEXT, 0.9, (0.5, 0.8, 0.8, 0.1)),
            (TABLE, 0.8, (0.5, 0.5, 0.8, 0.2)),
            (TEXT, 0.95, (0.5, 0.2, 0.8, 0.1)),
        ]
    )
    # A terceira consulta precede as outras duas na matriz de precedência.
    order[2, :] = 10.0
    order[:, 2] = -10.0
    regions = regions_from(logits, boxes, order, threshold=0.5, drop=())
    assert [r.label for r in regions] == ["text", "text", "table"]
    first = regions[0].bbox
    assert (first.x0, first.y0, first.x1, first.y1) == pytest.approx((0.1, 0.15, 0.9, 0.25))


def test_below_threshold_and_dropped_labels_leave_no_region():
    logits, boxes, order = _outputs(
        [
            (HEADER, 0.9, (0.5, 0.05, 0.3, 0.05)),
            (TEXT, 0.3, (0.5, 0.5, 0.8, 0.2)),
            (TEXT, 0.7, (0.5, 0.8, 0.8, 0.1)),
        ]
    )
    regions = regions_from(logits, boxes, order, threshold=0.5, drop=("header",))
    assert [r.label for r in regions] == ["text"]


def test_a_query_enters_once_with_its_best_class():
    """O grafo pontua cada consulta em 25 classes; a mesma caixa não vira duas regiões."""
    logits, boxes, order = _outputs([(TEXT, 0.8, (0.5, 0.5, 0.8, 0.2))])
    logits[0, LABELS.index("paragraph_title")] = np.log(0.6 / 0.4)
    regions = regions_from(logits, boxes, order, threshold=0.5, drop=())
    assert [r.label for r in regions] == ["text"]


def test_boxes_are_clipped_to_the_page_and_empty_ones_dropped():
    logits, boxes, order = _outputs(
        [(TEXT, 0.9, (0.0, 0.5, 0.4, 0.2)), (TEXT, 0.9, (0.5, 0.5, 0.0, 0.0))]
    )
    regions = regions_from(logits, boxes, order, threshold=0.5, drop=())
    assert len(regions) == 1
    assert regions[0].bbox.x0 == 0.0


def test_a_region_inside_another_is_read_once():
    """A lista de referências e o item dela: fica a maior, e o texto sai uma vez."""
    ref, item = LABELS.index("reference"), LABELS.index("reference_content")
    logits, boxes, order = _outputs(
        [(ref, 0.9, (0.5, 0.5, 0.8, 0.4)), (item, 0.9, (0.5, 0.45, 0.7, 0.1))]
    )
    regions = regions_from(logits, boxes, order, threshold=0.5, drop=())
    assert [r.label for r in regions] == ["reference"]


def test_an_inline_formula_inside_text_leaves_and_a_figure_beside_a_table_stays():
    formula, image = LABELS.index("inline_formula"), LABELS.index("image")
    logits, boxes, order = _outputs(
        [
            (TEXT, 0.9, (0.5, 0.2, 0.8, 0.1)),
            (formula, 0.9, (0.5, 0.2, 0.1, 0.05)),
            (TABLE, 0.9, (0.5, 0.6, 0.8, 0.3)),
            (image, 0.9, (0.5, 0.6, 0.6, 0.2)),
        ]
    )
    regions = regions_from(logits, boxes, order, threshold=0.5, drop=())
    assert [r.label for r in regions] == ["text", "table", "image"]


def test_a_dropped_label_does_not_take_what_it_covers():
    """O cabeçalho descartado sai antes da sobreposição: o título que ele cobre fica."""
    title = LABELS.index("paragraph_title")
    logits, boxes, order = _outputs(
        [(HEADER, 0.9, (0.5, 0.05, 0.8, 0.08)), (title, 0.9, (0.5, 0.05, 0.4, 0.04))]
    )
    regions = regions_from(logits, boxes, order, threshold=0.5, drop=("header",))
    assert [r.label for r in regions] == ["paragraph_title"]
