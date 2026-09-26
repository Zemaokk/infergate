import asyncio
from types import SimpleNamespace

import pytest

from infergate import token_bucket
from infergate.token_bucket import TokenBucket, TokenBucketLimiter


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    clock = SimpleNamespace(now=0.0)
    # Replace only this module's clock; leave asyncio's real clock untouched.
    monkeypatch.setattr(
        token_bucket, "time", SimpleNamespace(monotonic=lambda: clock.now)
    )
    return clock


def test_bucket_starts_full_and_rejects_excess(clock: SimpleNamespace) -> None:
    bucket = TokenBucket(capacity=2, rate=1)

    assert bucket.consume()
    assert bucket.consume()
    assert not bucket.consume()
    assert not bucket.consume()


def test_rejected_request_preserves_fractional_refill(clock: SimpleNamespace) -> None:
    bucket = TokenBucket(capacity=1, rate=1)
    assert bucket.consume()

    clock.now = 0.5
    assert not bucket.consume()

    clock.now = 1.0
    assert bucket.consume()
    assert not bucket.consume()


def test_long_idle_refill_is_capped_at_capacity(clock: SimpleNamespace) -> None:
    bucket = TokenBucket(capacity=2, rate=1)
    assert bucket.consume()
    assert bucket.consume()

    clock.now = 100.0
    assert bucket.consume()
    assert bucket.consume()
    assert not bucket.consume()


def test_limiter_creates_and_reuses_independent_key_buckets(
    clock: SimpleNamespace,
) -> None:
    limiter = TokenBucketLimiter(capacity=1, rate=1)

    assert limiter.allow("alice", 1)
    assert not limiter.allow("alice", 1)
    assert limiter.allow("bob", 1)
    assert not limiter.allow("alice", 1)
    assert not limiter.allow("bob", 1)

    clock.now = 1.0
    assert limiter.allow("alice", 1)
    assert limiter.allow("bob", 1)


@pytest.mark.asyncio
async def test_same_event_loop_requests_share_last_token(clock: SimpleNamespace) -> None:
    limiter = TokenBucketLimiter(capacity=1, rate=1)
    start = asyncio.Event()

    async def request() -> bool:
        await start.wait()
        return limiter.allow("alice", 1)

    tasks = [asyncio.create_task(request()) for _ in range(10)]
    start.set()
    results = await asyncio.gather(*tasks)

    assert results.count(True) == 1
    assert results.count(False) == 9
