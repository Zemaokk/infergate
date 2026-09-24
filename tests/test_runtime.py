from infergate.runtime import BACKEND_TIMEOUT


def test_backend_timeout_policy():
    assert BACKEND_TIMEOUT.connect == 5.0
    assert BACKEND_TIMEOUT.pool == 5.0
    assert BACKEND_TIMEOUT.write == 30.0
    assert BACKEND_TIMEOUT.read == 30.0
