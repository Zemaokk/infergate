import math
import time


class TokenBucket:
    def __init__(self, capacity: float, rate: float):
        self.capacity = capacity
        self.rate = rate  # token per sec
        self.tokens = capacity
        self.last_update = time.monotonic()

    def consume(self, price: float = 1) -> bool:
        # check price
        if not math.isfinite(price) or price <= 0:
            raise ValueError("price must be finite and greater than zero")

        now = time.monotonic()
        elapse = now - self.last_update
        self.last_update = now

        # refill
        self.tokens = min(self.capacity, elapse * self.rate + self.tokens)

        # check
        if self.tokens >= price:
            self.tokens -= price
            return True
        else:
            return False


class TokenBucketLimiter:
    def __init__(self, capacity: float, rate: float):
        self.capacity = capacity
        self.rate = rate
        self.buckets: dict[str, TokenBucket] = {}

    def register(self, key: str):
        self.buckets[key] = TokenBucket(self.capacity, self.rate)

    def allow(self, key: str, price: float) -> bool:
        if key not in self.buckets:
            self.register(key)
        return self.buckets[key].consume(price)
