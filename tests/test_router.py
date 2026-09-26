import pytest

from infergate.health import HealthManager
from infergate.router import Backend, NoBackendAvailableError, RoundRobinRouter


def test_example_router():
    router = RoundRobinRouter(
        {"model": [Backend("id_A", "url_A"), Backend("id_B", "url_B")]}
    )
    for i in range(5):
        if i in (0, 2, 4):
            assert router.select("model") == Backend("id_A", "url_A")
        if i in (1, 3):
            assert router.select("model") == Backend("id_B", "url_B")


def test_two_models():
    router = RoundRobinRouter(
        {
            "model_1": [Backend("id_1A", "url_1A"), Backend("id_1B", "url_1B")],
            "model_2": [Backend("id_2A", "url_2A"), Backend("id_2B", "url_2B")],
        }
    )

    assert router.select("model_1") == Backend("id_1A", "url_1A")
    assert router.select("model_2") == Backend("id_2A", "url_2A")


def test_after_failure():
    router = RoundRobinRouter(
        {"model": [Backend("id_A", "url_A"), Backend("id_B", "url_B")]}
    )
    assert router.select("model") == Backend("id_A", "url_A")
    with pytest.raises(NoBackendAvailableError):
        router.select("fake_model")
    assert router.select("model") == Backend("id_B", "url_B")


def test_error_no_model():
    router = RoundRobinRouter(
        {"model": [Backend("id_A", "url_A"), Backend("id_B", "url_B")]}
    )
    with pytest.raises(NoBackendAvailableError):
        router.select("fake_model")


def test_error_blank_backendlist():
    router = RoundRobinRouter({"model": []})
    with pytest.raises(NoBackendAvailableError):
        router.select("model")


def test_unhealthy_backend_is_skipped_and_recovery_restores_rotation():
    health = HealthManager(["id_A", "id_B"])
    health.record_probe("id_A", True)
    health.record_probe("id_B", True)
    router = RoundRobinRouter(
        {"model": [Backend("id_A", "url_A"), Backend("id_B", "url_B")]},
        health,
    )

    assert router.select("model").id == "id_A"

    health.record_probe("id_A", False)
    assert router.select("model").id == "id_B"
    assert router.select("model").id == "id_B"

    health.record_probe("id_A", True)
    assert router.select("model").id == "id_A"
    assert router.select("model").id == "id_B"


def test_no_healthy_backend_does_not_advance_cursor():
    health = HealthManager(["id_A", "id_B"])
    router = RoundRobinRouter(
        {"model": [Backend("id_A", "url_A"), Backend("id_B", "url_B")]},
        health,
    )

    with pytest.raises(NoBackendAvailableError):
        router.select("model")
    assert router.cursors["model"] == 0


    health.record_probe("id_B", True)
    assert router.select("model").id == "id_B"
    assert router.cursors["model"] == 0

    health.record_probe("id_B", False)
    with pytest.raises(NoBackendAvailableError):
        router.select("model")
    assert router.cursors["model"] == 0


@pytest.mark.parametrize("with_health", [False, True])
def test_exclusion_skips_backend_without_mutating_or_retaining_input(with_health):
    health = HealthManager(["a", "b"]) if with_health else None
    if health is not None:
        health.record_probe("a", True)
        health.record_probe("b", True)
    router = RoundRobinRouter(
        {"model": [Backend("a", "http://a"), Backend("b", "http://b")]}, health
    )
    excluded = {"a"}

    assert router.select("model", excluded).id == "b"
    assert excluded == {"a"}
    assert router.select("model").id == "a"


@pytest.mark.parametrize("with_health", [False, True])
def test_all_excluded_leaves_nonzero_cursor_unchanged(with_health):
    health = HealthManager(["a", "b"]) if with_health else None
    if health is not None:
        health.record_probe("a", True)
        health.record_probe("b", True)
    router = RoundRobinRouter(
        {"model": [Backend("a", "http://a"), Backend("b", "http://b")]}, health
    )
    assert router.select("model").id == "a"
    assert router.cursors["model"] == 1

    with pytest.raises(NoBackendAvailableError):
        router.select("model", {"a", "b"})

    assert router.cursors["model"] == 1
    assert router.select("model", set()).id == "b"


def test_exclusion_and_health_are_combined_without_changing_callers_set():
    health = HealthManager(["a", "b", "c"])
    health.record_probe("a", True)
    health.record_probe("c", True)
    router = RoundRobinRouter(
        {"model": [Backend(key, f"http://{key}") for key in ("a", "b", "c")]},
        health,
    )
    excluded = {"a"}

    assert router.select("model", excluded).id == "c"
    assert excluded == {"a"}

    with pytest.raises(NoBackendAvailableError):
        router.select("model", {"a", "c"})
