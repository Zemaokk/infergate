from infergate.health import HealthManager


def test_health_manager_starts_unhealthy_and_unknown_id_is_unhealthy() -> None:
    health = HealthManager(["backend-a", "backend-b"])

    assert not health.is_healthy("backend-a")
    assert not health.is_healthy("unknown")


def test_latest_probe_result_controls_health() -> None:
    health = HealthManager(["backend-a"])

    health.record_probe("backend-a", True)
    assert health.is_healthy("backend-a")

    health.record_probe("backend-a", False)
    assert not health.is_healthy("backend-a")

    health.record_probe("backend-a", True)
    assert health.is_healthy("backend-a")
