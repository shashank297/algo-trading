from itertools import permutations
from types import SimpleNamespace
import sys

from tools.nifty200_pit.ocr import extract_ocr_pages


def test_ocr_cell_order_does_not_depend_on_backend_permutation(monkeypatch):
    cells = [
        ([[0, -1], [3, -1], [3, 1], [0, 1]], 'FIRST', 1.0),
        ([[5, -4], [8, -4], [8, 16], [5, 16]], 'SAME', 1.0),
        ([[5, 5], [8, 5], [8, 7], [5, 7]], 'SAME', 1.0),
    ]
    bitmap = SimpleNamespace(to_numpy=lambda: None, close=lambda: None)
    page = SimpleNamespace(render=lambda **_: bitmap, close=lambda: None)

    class Document:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def __len__(self):
            return 1

        def __getitem__(self, _):
            return page

    monkeypatch.setitem(sys.modules, 'pypdfium2', SimpleNamespace(PdfDocument=lambda _: Document()))
    outputs = set()
    for order in permutations(cells):
        monkeypatch.setitem(sys.modules, 'rapidocr_onnxruntime', SimpleNamespace(
            RapidOCR=lambda: lambda _: (list(order), None)))
        outputs.add(tuple(extract_ocr_pages('fixture.pdf')))
    assert len(outputs) == 1
