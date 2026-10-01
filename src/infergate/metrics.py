from collections.abc import Iterable
from functools import partial

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from infergate.concurrency_limiter import ConcurrencyLimiter
from infergate.health import HealthManager
from infergate.observability import RequestObservation


class GatewayMetrics:
    """Each app owns its registry; no global metrics or caller-specific labels."""

    def __init__(self, concurrency_limiter: ConcurrencyLimiter) -> None:
        self.registry = CollectorRegistry()
        self.active_requests = Gauge(
            "infergate_active_requests",
            "Currently occupied global concurrency slots in this gateway process.",
            registry=self.registry,
        )
        # 每次抓取读取真实名额占用，不另维护 inc/dec 计数。
        self.active_requests.set_function(
            lambda: concurrency_limiter.limit - concurrency_limiter.available
        )
        self.requests = Counter(
            "infergate_requests_total",
            "Business requests finalized after response execution and cleanup.",
            ("route", "status", "outcome", "reason"),
            registry=self.registry,
        )
        self.duration = Histogram(
            "infergate_request_duration_seconds",
            "Gateway-observed request duration including response cleanup.",
            ("route", "outcome"),
            # Seconds; include long streams rather than only subsecond responses.
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
            registry=self.registry,
        )
        self.first_byte = Histogram(
            "infergate_request_first_byte_seconds",
            "Time from request entry to first nonempty backend stream chunk; not TTFT.",
            ("route", "outcome"),
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
            registry=self.registry,
        )
        self.backend_attempts = Counter(
            "infergate_backend_attempts_total",
            "Finalized backend attempts, including failed fallback attempts.",
            ("backend", "outcome"),
            registry=self.registry,
        )
        self.backend_attempt_duration = Histogram(
            "infergate_backend_attempt_duration_seconds",
            "Backend attempt duration including cleanup for opened streams.",
            ("backend", "outcome"),
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
            registry=self.registry,
        )

    def track_backend_health(
        self, backend_ids: Iterable[str], health_manager: HealthManager
    ) -> None:
        backend_health = Gauge(
            "infergate_backend_healthy",
            "Current routing health state (1 healthy, 0 unhealthy or not yet probed).",
            ("backend",),
            registry=self.registry,
        )
        for backend_id in sorted(set(backend_ids)):
            # 固定每个 backend 的 ID，抓取时只读现有状态，不发起探测。
            backend_health.labels(backend=backend_id).set_function(
                partial(health_manager.is_healthy, backend_id)
            )

    def record_request(self, observation: RequestObservation) -> None:
        # Caller submits only when finish() returns True. Do not count pending work.
        if not observation.is_finished:
            return
        route = "/v1/chat/completions"
        self.requests.labels(
            route=route,
            status=str(observation.status_code)
            if observation.status_code is not None
            else "none",
            outcome=observation.outcome,
            reason=observation.reason or "none",
        ).inc()
        self.duration.labels(route=route, outcome=observation.outcome).observe(
            observation.total_time
        )
        # None 表示没有首字节样本；0.0 则是有效测量，不能用真假判断跳过。
        # 等请求定稿后提交，才能按最终 outcome 区分成功与中途失败的流。
        if observation.first_byte_sec is not None:
            self.first_byte.labels(route=route, outcome=observation.outcome).observe(
                observation.first_byte_sec
            )
        # 请求定稿时统一提交；每次尝试使用自己的后端、结果和耗时。
        for attempt in observation.backend_attempts:
            if not attempt.is_finished:
                continue
            self.backend_attempts.labels(
                backend=attempt.backend_id, outcome=attempt.outcome
            ).inc()
            self.backend_attempt_duration.labels(
                backend=attempt.backend_id, outcome=attempt.outcome
            ).observe(attempt.total_time)
