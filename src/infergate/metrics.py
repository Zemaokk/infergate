from prometheus_client import CollectorRegistry, Counter, Histogram

from infergate.observability import RequestObservation


class GatewayMetrics:
    """Each app owns its registry; no global metrics or caller-specific labels."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
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

    def record_request(self, observation: RequestObservation) -> None:
        # Caller submits only when finish() returns True. Do not count pending work.
        if not observation.is_finish or observation.total_time is None:
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
