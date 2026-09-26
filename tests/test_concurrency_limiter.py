from infergate.concurrency_limiter import ConcurrencyLimiter


def test_capacity_is_reusable_after_release():
    limiter = ConcurrencyLimiter(2)
    assert limiter.available == 2
    assert limiter.try_acquire()
    assert limiter.try_acquire()
    assert not limiter.try_acquire()
    assert limiter.available == 0
    limiter.release()
    assert limiter.try_acquire()
    assert not limiter.try_acquire()
    limiter.release()
    limiter.release()
    assert limiter.available == 2
