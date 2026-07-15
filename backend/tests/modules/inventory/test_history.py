import uuid
from datetime import UTC, datetime

from app.modules.audit.api.router import label_action, serialize, summarize_value
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.infrastructure.models import User


def test_history_labels_known_actions_in_spanish() -> None:
    assert label_action("invoice_registered") == "Factura registrada"
    assert label_action("unknown_internal_action") == "Unknown Internal Action"


def test_history_summary_prioritizes_operational_fields() -> None:
    summary = summarize_value(
        {
            "internal": "ignored when enough business keys exist",
            "invoice": "001-001-000000686",
            "chain": "Favorita",
            "units": 12,
            "status": "registered",
        }
    )

    assert (
        summary
        == "invoice: 001-001-000000686 · chain: Favorita · units: 12 · status: registered"
    )


def test_history_serializer_returns_reader_friendly_audit_event() -> None:
    user = User(
        id=uuid.uuid4(),
        username="principal",
        full_name="José Escobar",
        role="principal",
        password_hash="hash",
    )
    audit = AuditLog(
        id=uuid.uuid4(),
        actor_user_id=user.id,
        action="purchase_order_created",
        entity_type="purchase_order",
        entity_id="OC-001",
        reason="Registro inicial",
        new_value={"number": "OC-001", "chain": "Favorita"},
        occurred_at=datetime(2026, 7, 14, 14, 30, tzinfo=UTC),
        ip_address="127.0.0.1",
    )

    payload = serialize(audit, user)

    assert payload["actor"] == "José Escobar"
    assert payload["action_label"] == "OC registrada"
    assert payload["module"] == "Órdenes de compra"
    assert payload["summary"] == "number: OC-001 · chain: Favorita"
