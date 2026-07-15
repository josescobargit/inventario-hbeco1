from app.modules.inventory.api.router import movement_delta, movement_label


def test_movement_delta_detects_changed_stock_bucket() -> None:
    field, delta = movement_delta(
        {"physical_confirmed": 10, "version": 1},
        {"physical_confirmed": 7, "version": 2},
    )

    assert field == "physical_confirmed"
    assert delta == -3


def test_movement_label_uses_operational_spanish_label() -> None:
    assert movement_label("general_entry") == "Entrada general"
    assert movement_label("unknown_internal_type") == "Unknown Internal Type"
