"""容器状态 exporter：只读地查询 Docker，把 InferGate 两个 compose 项目里每个容器的状态暴露成 Prometheus 指标。

回答"它为什么不工作了"：停了、崩了（退出码、OOM）、还是活着但卡住了（unhealthy）。
采用自定义 Collector：不预先保存数值，每次被 Prometheus 抓取时才读取 Docker，被删除的容器会自然消失。
"""

import time
from datetime import datetime

import docker
from prometheus_client import start_http_server
from prometheus_client.core import REGISTRY, CounterMetricFamily, GaugeMetricFamily

PROJECTS = {"infergate-app", "infergate-observability"}
HEALTH_STATUSES = ["healthy", "unhealthy", "starting", "none"]
LABELS = ["project", "service"]
PORT = 9101


def _timestamp(rfc3339: str) -> float | None:
    """Docker 的时间是 RFC 3339（纳秒精度）；从未启动过的容器是 0001-01-01，返回 None。"""
    if rfc3339.startswith("0001-01-01"):
        return None
    return datetime.fromisoformat(rfc3339).timestamp()


class ContainerCollector:
    def __init__(self, client: docker.DockerClient):
        self.client = client

    def collect(self):
        running = GaugeMetricFamily(
            "container_running",
            "Whether the container is running (1) or not (0)",
            labels=LABELS,
        )
        health = GaugeMetricFamily(
            "container_health",
            "Health check status, one series per status, 1 for the current one. "
            "Only meaningful when container_running is 1; not running or no healthcheck -> none",
            labels=LABELS + ["status"],
        )
        restarts = CounterMetricFamily(
            "container_restarts",  # 输出时自动加 _total 后缀
            "Number of times Docker restarted the container",
            labels=LABELS,
        )
        exit_code = GaugeMetricFamily(
            "container_last_exit_code",
            "Exit code of the last exit (143 = SIGTERM, stopped; 137 = SIGKILL, e.g. OOM)",
            labels=LABELS,
        )
        oom_killed = GaugeMetricFamily(
            "container_oom_killed",
            "Whether the last exit was an out-of-memory kill (1) or not (0)",
            labels=LABELS,
        )
        started_at = GaugeMetricFamily(
            "container_started_at_seconds",
            "Unix time when the container last started",
            labels=LABELS,
        )

        # Docker 的多个 label 过滤条件是"同时满足"，无法表达"项目 A 或 B"，
        # 所以先取所有 compose 容器，再在这里按项目名筛选
        for c in self.client.containers.list(
            all=True, filters={"label": "com.docker.compose.project"}
        ):
            project = c.labels.get("com.docker.compose.project")
            if project not in PROJECTS:
                continue
            labels = [project, c.labels.get("com.docker.compose.service", "unknown")]
            state = c.attrs["State"]
            is_running = bool(state["Running"])

            running.add_metric(labels, 1 if is_running else 0)

            # 容器停止后 Docker 保留的是最后一次检查结果，已经过时，统一记为 none
            current = (
                state.get("Health", {}).get("Status", "none") if is_running else "none"
            )
            for s in HEALTH_STATUSES:
                health.add_metric(labels + [s], 1 if current == s else 0)

            restarts.add_metric(labels, c.attrs["RestartCount"])
            exit_code.add_metric(labels, state["ExitCode"])
            oom_killed.add_metric(labels, 1 if state["OOMKilled"] else 0)

            ts = _timestamp(state["StartedAt"])
            if ts is not None:
                started_at.add_metric(labels, ts)

        yield from (running, health, restarts, exit_code, oom_killed, started_at)


def main() -> None:
    REGISTRY.register(ContainerCollector(docker.from_env()))
    start_http_server(PORT)
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
