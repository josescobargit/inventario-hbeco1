import csv
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.modules.catalog.infrastructure.models import Product
from app.modules.inventory.infrastructure.models import (
    InventoryPositionModel,
    Warehouse,
)


SEED_PATH = Path("database/seed_data/products_seed.csv")


def load_rows() -> list[dict[str, object]]:
    with SEED_PATH.open(encoding="utf-8", newline="") as seed_file:
        source_rows = list(csv.DictReader(seed_file))

    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for line_number, source in enumerate(source_rows, start=2):
        sku = (source.get("sku") or "").strip()
        if not sku or sku in seen:
            raise ValueError(f"SKU vacío o duplicado en la fila {line_number}: {sku}")
        seen.add(sku)
        units_per_box = int(source["units_per_box"])
        if units_per_box not in {6, 12, 288}:
            raise ValueError(f"UXC inválida para {sku}: {units_per_box}")
        rows.append(
            {
                "sku": sku,
                "name": source["name"].strip(),
                "description": source["description"].strip() or None,
                "category": source["category"].strip(),
                "barcode": source["barcode"].strip() or None,
                "contifico_aux_code": source["contifico_aux_code"].strip() or None,
                "cost": Decimal(source["cost"]),
                "units_per_box": units_per_box,
                "is_active": source["is_active"].lower() == "true",
            }
        )
    if len(rows) != 29:
        raise ValueError(f"La semilla debe contener 29 productos; contiene {len(rows)}")
    return rows


def main() -> None:
    rows = load_rows()
    with SessionLocal.begin() as db:
        warehouse = db.scalar(select(Warehouse).where(Warehouse.code == "principal"))
        if warehouse is None:
            raise RuntimeError("No existe la bodega principal. Aplica las migraciones.")

        for values in rows:
            product = db.scalar(select(Product).where(Product.sku == values["sku"]))
            if product is None:
                product = Product(**values)
                db.add(product)
                db.flush()
            else:
                for field, value in values.items():
                    setattr(product, field, value)

            position = db.scalar(
                select(InventoryPositionModel).where(
                    InventoryPositionModel.warehouse_id == warehouse.id,
                    InventoryPositionModel.product_id == product.id,
                )
            )
            if position is None:
                db.add(
                    InventoryPositionModel(
                        warehouse_id=warehouse.id,
                        product_id=product.id,
                    )
                )

    print("catalog_seed=ok products=29 physical_stock_imported=false")


if __name__ == "__main__":
    main()
