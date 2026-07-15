from app.modules.returns.api.router import LineInput


def test_problem_return_has_explicit_disposition() -> None:
    line = LineInput(
        sku="AE001", quantity=2, disposition="in_review", notes="Etiqueta dañada"
    )
    assert line.disposition == "in_review"
