"""Opt-in regression suite for the customer's actual, unmodified OC files.

REAL_OC_ZIP=/absolute/path/Archivo.zip PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/modules/commercial/test_real_order_formats.py -q
The files stay outside the repository. Each OC is checked independently.
"""

import os
import zipfile
from types import SimpleNamespace

import pytest

from app.modules.commercial.ingestion import parse_file
from app.modules.commercial.processing import recognition_evidence

CASES = [
    (
        "OC 26003023.pdf",
        "INDUSTRIAL DANEC",
        "26003023",
        "2026-09-14",
        [360, 480, 168, 240],
        "units",
    ),
    (
        "1 FAVORITA OC 2 OCT .pdf",
        "CORPORACIÓN FAVORITA",
        "100627494678",
        "2026-10-01",
        [30],
        "boxes",
    ),
    (
        "2 FAVORITA OC 2 OCT.pdf",
        "CORPORACIÓN FAVORITA",
        "100627494679",
        "2026-10-01",
        [10, 6, 6, 10, 125, 35, 10, 15, 60, 30],
        "boxes",
    ),
    (
        "orden-compra-7273840.pdf",
        "FARCOMED",
        "7273840",
        "2026-09-29",
        [12, 516, 936],
        "units",
    ),
    (
        "OC_005918936 (1).pdf",
        "LIRIS DEL PORTAL",
        "OC_005918936",
        "2026-10-05",
        [1, 1, 1, 1],
        "boxes",
    ),
    ("RA335941.pdf", "GERARDO ORTIZ", "5601875028", "2026-09-25", [12, 6], "units"),
    ("OC 4500374870.PDF", "TUTI", "4500374870", "2026-09-28", [2, 11, 10, 10], "boxes"),
    (
        "OC TIA 3001037437.pdf",
        "TIA",
        "3001037437",
        "2026-09-15",
        [22, 139, 140, 89, 58, 24],
        "boxes",
    ),
    (
        "pedidos_125167 (1).pdf",
        "CORPORACIÓN EL ROSADO",
        "4618533590",
        "2026-09-25",
        [72, 72, 12, 12, 25, 200, 90, 24],
        "boxes",
    ),
    (
        "pedidos_125167 (1).pdf",
        "CORPORACIÓN EL ROSADO",
        "4618533654",
        "2026-09-25",
        [9, 1, 19, 4, 31, 10, 6],
        "boxes",
    ),
    (
        "WhatsApp Image 2026-09-30 at 14.35.08.jpeg",
        "CORPORACIÓN EL ROSADO",
        "4618533654",
        "2026-09-25",
        [9, 1, 19, 4, 31, 10, 6],
        "boxes",
    ),
]


@pytest.mark.skipif(
    not os.environ.get("REAL_OC_ZIP"), reason="Requires the user's real OC archive"
)
@pytest.mark.parametrize(
    "filename,chain,order_number,order_date,quantities,unit",
    CASES,
    ids=[f"{c[1]}-{c[2]}-{i}" for i, c in enumerate(CASES)],
)
def test_real_order(filename, chain, order_number, order_date, quantities, unit):
    with zipfile.ZipFile(os.environ["REAL_OC_ZIP"]) as archive:
        content = archive.read(filename)
    # Rename the input to prove recognition does not depend on its filename.
    anonymous_name = "documento.jpeg" if filename.endswith(".jpeg") else "documento.pdf"
    _, method, _, sources, _ = parse_file(anonymous_name, content)
    document = SimpleNamespace(id="test", filename=anonymous_name, method=method)
    rows = [
        recognition_evidence(
            SimpleNamespace(
                id=str(i), row_number=i, source=raw, corrections={}, revision=1
            ),
            document,
        )
        for i, raw in enumerate(sources, 1)
    ]
    selected = [r for r in rows if r["order_number"] == order_number]
    assert len(selected) == len(quantities)
    assert all(
        r["chain"] == chain and r["kind"] == "order" and r["date"] == order_date
        for r in selected
    )
    assert [r["units"] for r in selected] == quantities
    assert all(r["issues"] == [] and r["source"]["unit"] == unit for r in selected)
    if chain == "LIRIS DEL PORTAL":
        assert all(r["source"]["units_per_box"] == 12 for r in selected)
    if chain == "INDUSTRIAL DANEC":
        assert all(r["buyer_ruc"] == "1790040968001" for r in selected)
    if filename == "pedidos_125167 (1).pdf":
        assert {r["order_number"] for r in rows} == {"4618533590", "4618533654"}
        assert len(rows) == 15
