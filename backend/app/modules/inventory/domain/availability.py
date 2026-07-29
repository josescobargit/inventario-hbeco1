from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InventoryPosition:
    physical_confirmed: int
    reserved: int
    invoiced_not_dispatched: int
    blocked_by_incident: int

    def __post_init__(self) -> None:
        for field_name, value in vars_for_slots(self).items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"{field_name} debe ser un entero mayor o igual a cero"
                )

    @property
    def available_to_invoice(self) -> int:
        return self.physical_confirmed - self.reserved - self.blocked_by_incident

    def require_available(self, quantity: int) -> None:
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("La cantidad debe ser un entero mayor que cero")
        if quantity > self.available_to_invoice:
            raise InsufficientAvailabilityError(
                requested=quantity,
                available=self.available_to_invoice,
            )


class InsufficientAvailabilityError(ValueError):
    def __init__(self, requested: int, available: int) -> None:
        self.requested = requested
        self.available = available
        super().__init__(
            f"Se solicitaron {requested} unidades, pero solo hay {available} disponibles."
        )


def vars_for_slots(position: InventoryPosition) -> dict[str, int]:
    return {
        "physical_confirmed": position.physical_confirmed,
        "reserved": position.reserved,
        "invoiced_not_dispatched": position.invoiced_not_dispatched,
        "blocked_by_incident": position.blocked_by_incident,
    }
