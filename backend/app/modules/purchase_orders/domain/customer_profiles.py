import json
import unicodedata
from functools import lru_cache
from pathlib import Path


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    return (
        "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )
        .strip()
        .upper()
    )


@lru_cache(maxsize=1)
def configured_profiles() -> list[dict]:
    path = Path(__file__).with_name("customer_profiles.json")
    with path.open(encoding="utf-8") as source:
        payload = json.load(source)
    return payload.get("profiles", [])


def aliases_for_chain(chain_name: str) -> list[dict[str, str]]:
    normalized_chain = _normalize(chain_name)
    for profile in configured_profiles():
        if normalized_chain in {
            _normalize(value) for value in profile.get("chain_names", [])
        }:
            return [
                {
                    "source_text": alias["code"],
                    "source_text_normalized": _normalize(alias["code"]),
                    "detected_code": alias["code"],
                    "sku": alias["sku"],
                }
                for alias in profile.get("product_aliases", [])
            ]
    return []


def chain_evidence_aliases() -> list[tuple[str, str, str | None]]:
    evidence = []
    for profile in configured_profiles():
        chain_names = profile.get("chain_names", [])
        if not chain_names:
            continue
        for alias in profile.get("product_aliases", []):
            evidence.append((chain_names[0], _normalize(alias["code"]), alias["code"]))
    return evidence
