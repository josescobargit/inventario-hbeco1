from app.modules.purchase_orders.domain.customer_profiles import (
    aliases_for_chain,
    chain_evidence_aliases,
)


def test_tia_profile_contains_confirmed_homologation_without_global_aliases() -> None:
    aliases = aliases_for_chain("Tía")
    assert {(alias["detected_code"], alias["sku"]) for alias in aliases} == {
        ("163818000", "AR004"),
        ("166451000", "ACP001"),
        ("168929000", "AR003"),
        ("168933000", "AR001"),
    }
    assert aliases_for_chain("TUTI") == []
    assert aliases_for_chain("Corporación Favorita") == []


def test_configured_codes_can_propose_their_profile_chain() -> None:
    evidence = chain_evidence_aliases()
    assert ("TIA", "163818000", "163818000") in evidence
