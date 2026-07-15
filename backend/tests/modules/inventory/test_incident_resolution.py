from app.modules.incidents.api.router import Resolution


def test_retry_dispatch_is_an_explicit_decision() -> None:
    resolution = Resolution(
        decision="retry_dispatch",
        reason="Producto localizado y se despachará nuevamente",
    )
    assert resolution.decision == "retry_dispatch"
