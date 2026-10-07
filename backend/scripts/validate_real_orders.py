"""Sequential, read-only recognition checks against a user's real OC archive.

Usage: PYTHONPATH=backend .venv/bin/python backend/scripts/validate_real_orders.py Archivo.zip output.json
No documents are imported into the database by this script.
"""

import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

from app.modules.commercial.ingestion import parse_file
from app.modules.commercial.processing import recognition_evidence


def validate(archive_path, output):
    results = []
    with zipfile.ZipFile(archive_path) as archive:
        for entry in archive.infolist():
            if entry.is_dir() or entry.filename.startswith("__MACOSX/"):
                continue
            filename = Path(entry.filename).name
            print(f"Procesando individualmente: {filename}", flush=True)
            try:
                _, method, text, rows, warnings = parse_file(
                    filename, archive.read(entry)
                )
                document = SimpleNamespace(
                    id=filename, filename=filename, method=method
                )
                groups = {}
                for index, raw in enumerate(rows, 1):
                    row = SimpleNamespace(
                        id=str(index),
                        row_number=index,
                        source=raw,
                        corrections={},
                        revision=1,
                    )
                    evidence = recognition_evidence(row, document)
                    key = (
                        evidence["chain"],
                        evidence["kind"],
                        evidence["order_number"],
                        evidence["date"],
                    )
                    group = groups.setdefault(
                        key,
                        {
                            "archivo": filename,
                            "cadena": key[0],
                            "tipo": key[1],
                            "oc": key[2],
                            "fecha": key[3],
                            "ruc": evidence["buyer_ruc"],
                            "productos": [],
                            "problemas": [],
                        },
                    )
                    group["productos"].append(
                        {
                            "descripcion": evidence["product_name"],
                            "cantidad": evidence["units"],
                            "unidad": raw.get("unit"),
                            "codigo": raw.get("code"),
                        }
                    )
                    group["problemas"].extend(evidence["issues"])
                for group in groups.values():
                    group["problemas"] = list(dict.fromkeys(group["problemas"]))
                    group["estado"] = "REVISAR" if group["problemas"] else "OK"
                    group["numero_productos"] = len(group["productos"])
                    results.append(group)
                    print(
                        f"  {group['cadena']} | {group['oc']} | {group['fecha']} | {group['numero_productos']} productos | {group['estado']}",
                        flush=True,
                    )
                # Evidence text is saved alongside the report for manual comparison.
                evidence_dir = Path(output).parent / "textos-oc"
                evidence_dir.mkdir(parents=True, exist_ok=True)
                (evidence_dir / (filename + ".txt")).write_text(
                    text or "", encoding="utf-8"
                )
            except Exception as exc:
                results.append(
                    {"archivo": filename, "estado": "ERROR", "problemas": [str(exc)]}
                )
    Path(output).write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return results


if __name__ == "__main__":
    validate(sys.argv[1], sys.argv[2])
