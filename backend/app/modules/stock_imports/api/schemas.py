import uuid
from pydantic import BaseModel, Field


class StockImportLineInput(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    counted_physical: int = Field(ge=0)
    position_version: int = Field(gt=0)


class StockImportCreate(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)
    lines: list[StockImportLineInput]


class StockImportDecision(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class StockImportResponse(BaseModel):
    id: uuid.UUID
    status: str
    total_products: int
