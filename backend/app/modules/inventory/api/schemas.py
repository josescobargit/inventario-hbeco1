from pydantic import BaseModel


class AvailabilityResponse(BaseModel):
    sku: str
    product_name: str
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
