class ConcurrencyLimiter:
    def __init__(self, limit: int):
        self.limit = limit
        self.available = limit

    def try_acquire(self) -> bool:
        if self.available >= 1:
            self.available -= 1
            return True
        else:
            return False

    def release(self) -> None:
        self.available = min(self.limit, self.available + 1)
