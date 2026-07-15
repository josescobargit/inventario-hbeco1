import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.catalog.infrastructure.models import Product
from app.modules.inventory.infrastructure.models import (
    InventoryPositionModel,
    Warehouse,
)
from app.modules.stock_imports.domain.csv_parser import (
    ImportError,
    parse_stock_csv,
    parse_stock_xlsx,
)


router = APIRouter(prefix="/stock-imports", tags=["Conteos masivos"])
MAX_FILE_SIZE = 5 * 1024 * 1024


def inventory_rows(db: Session):
    return db.execute(
        select(Product, InventoryPositionModel)
        .join(InventoryPositionModel, InventoryPositionModel.product_id == Product.id)
        .join(Warehouse, Warehouse.id == InventoryPositionModel.warehouse_id)
        .where(Product.is_active.is_(True), Warehouse.code == "principal")
        .order_by(Product.sku)
    ).all()


@router.get("/template")
def download_template(
    _user: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> Response:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["SKU", "Producto", "Stock_Fisico"])
    for product, position in inventory_rows(db):
        writer.writerow([product.sku, product.name, position.physical_confirmed])
    return Response(
        content=output.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="conteo_stock_fisico.csv"'
        },
    )


@router.post("/preview")
async def preview_import(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
) -> dict:
    filename = (file.filename or "").lower()
    if not filename.endswith((".csv", ".xlsx")):
        raise HTTPException(
            status_code=422, detail="Carga un archivo CSV UTF-8 o XLSX."
        )
    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413, detail="El archivo supera el máximo permitido de 5 MB."
        )
    parsed, errors = (
        parse_stock_xlsx(content)
        if filename.endswith(".xlsx")
        else parse_stock_csv(content)
    )
    current = {
        product.sku: (product, position) for product, position in inventory_rows(db)
    }
    provided = {line.sku for line in parsed}
    for line in parsed:
        if line.sku not in current:
            errors.append(
                ImportError(
                    line.row, "SKU", line.sku, "El SKU no existe en el catálogo activo."
                )
            )
    for sku in sorted(set(current) - provided):
        errors.append(
            ImportError(None, "SKU", sku, "Falta este producto activo en el archivo.")
        )
    rows = []
    if not errors:
        for line in parsed:
            product, position = current[line.sku]
            rows.append(
                {
                    "row": line.row,
                    "sku": line.sku,
                    "product_name": product.name,
                    "current_physical": position.physical_confirmed,
                    "counted_physical": line.physical_confirmed,
                    "difference": line.physical_confirmed - position.physical_confirmed,
                    "position_version": position.version,
                }
            )
    return {
        "valid": not errors,
        "total_products": len(rows),
        "rows": rows,
        "errors": [
            {
                "row": item.row,
                "column": item.column,
                "sku": item.sku,
                "message": item.message,
            }
            for item in errors
        ],
    }
