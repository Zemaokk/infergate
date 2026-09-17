import pytest
from infergate.router import RoundRobinRouter, Backend, NoBackendAvailableError

def test_example_router():
    router = RoundRobinRouter(
        {
            "model": [
                Backend("id_A", "url_A"),
                Backend("id_B", "url_B")
            ]
        }
    )
    for i in range(5):
        if i in (0,2,4): assert router.select("model") == Backend("id_A", "url_A")
        if i in (1,3): assert router.select("model") == Backend("id_B", "url_B")

def test_two_models():
    router = RoundRobinRouter(
        {
            "model_1": [
                Backend("id_1A", "url_1A"),
                Backend("id_1B", "url_1B")
            ],
            "model_2": [
                Backend("id_2A", "url_2A"),
                Backend("id_2B", "url_2B")
            ]         
        }
    )

    assert router.select("model_1") == Backend("id_1A", "url_1A")
    assert router.select("model_2") == Backend("id_2A", "url_2A")

def test_after_failure():
    router = RoundRobinRouter(
        {
            "model": [
                Backend("id_A", "url_A"),
                Backend("id_B", "url_B")
            ]
        }
    )
    assert router.select("model") == Backend("id_A", "url_A")
    with pytest.raises(NoBackendAvailableError):
        router.select("fake_model")
    assert router.select("model") == Backend("id_B", "url_B")

def test_error_no_model():
    router = RoundRobinRouter(
        {
            "model": [
                Backend("id_A", "url_A"),
                Backend("id_B", "url_B")
            ]
        }
    )
    with pytest.raises(NoBackendAvailableError):
        router.select("fake_model")

def test_error_blank_backendlist():
    router = RoundRobinRouter(
        {
            "model": []
        }
    )
    with pytest.raises(NoBackendAvailableError):
        router.select("model")