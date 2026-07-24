import uuid

from pydantic import BaseModel


class AvailabilityResponse(BaseModel):
    id: uuid.UUID
    sku: str
    product_name: str
    barcode: str | None
    contifico_aux_code: str | None
    category: str
    physical_confirmed: int
    reserved: int
    invoiced_not_dispatched: int
    blocked_by_incident: int
    available_to_invoice: int
    units_per_box: int
    physical_boxes: float
    available_boxes: float
    status: str
