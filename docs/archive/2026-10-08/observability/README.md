# 本地 M3 观测栈

当前状态：2026-10-05 已通过 Docker Desktop 的真实联调与 Grafana 渲染检查。
9 个请求、10 次尝试的指标、日志和 trace 对应，最终并发占用为 0。
作者复述已完成，证据与范围见 [M3 验收记录](../docs/M3/ACCEPTANCE.md)。

## 1. 启动观测服务

需要可用的 Docker Engine 与 Compose。仓库根目录执行：

```bash
docker compose -f observability/compose.yaml config
docker compose -f observability/compose.yaml up -d
```

固定镜像版本：Prometheus 3.15.0、Jaeger 2.21.0、Grafana 13.2.3。
首次拉取镜像时需网络可用。服务入口：

| 服务 | 地址 | 用途 |
| --- | --- | --- |
| Prometheus | http://127.0.0.1:9090 | 抓取指标、查询时间序列 |
| Jaeger | http://127.0.0.1:16686 | 用日志 trace_id 定位请求时间轴 |
| OTLP 接收 | http://127.0.0.1:4318/v1/traces | 网关 exporter 地址 |
| Grafana | http://127.0.0.1:3000 | 指标仪表盘与 Jaeger 数据源 |

Grafana 本地演示账号为 `admin` / `infergate-local`。打开 InferGate 文件夹下的
“**InferGate 本地可观测性**”仪表盘。
数据源和仪表盘自动 provisioning，无需手动录入。

如果 DMG 安装后 `docker` 尚未加入 PATH，可只为当前终端设置：

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
```

本次验证使用 Docker Engine 29.8.2、随 Docker Desktop 提供的 Compose 5.5.1。
若 `docker compose` 插件尚未注册，可用
`/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose`
替代上述 `docker compose`，并保留 PATH 设置以找到凭据助手。

Prometheus 从容器访问 `host.docker.internal:8000/metrics`；网关运行在宿主机。
Compose 为 Linux 提供 host-gateway 映射，Mac Docker Desktop 也支持该主机名。
验收时网关绑定 `0.0.0.0:8000`，让容器能抓取；观测服务 UI 端口仅绑定宿主机
127.0.0.1。Prometheus 每 5 秒抓取，保存 24 小时的数据。Jaeger 使用默认
all-in-one 内存存储，重启会丢失 trace；Prometheus/Grafana 用命名卷保存数据。

## 2. 执行受控联调

停止自己已有的 8000/8001/8002 服务，确保端口空闲，然后执行：

```bash
uv run python scripts/verify_m3.py --output /tmp/infergate-m3-evidence.json
```

脚本先确认三个观测服务响应，再启动其自己管理的两个受控后端和网关。网关
健康探测间隔临时设为 3600 秒，在停止 A 后保持候选健康状态，确定性触发
fallback；不修改生产默认配置。脚本覆盖普通成功、流式完成、客户端断开、
拒绝、fallback、两个后端离线，并检查：

- 完成日志的 trace_id 能查询到 Jaeger trace；请求和 A/B span 的父子关系与
  outcome 匹配，不以 HTTP 200 代替流式最终结果。
- Prometheus 中请求/尝试计数与这些日志一致，结束后的并发占用恢复为 0。
- Grafana 自动加载指定仪表盘。

脚本在首轮成功请求后等待一个抓取周期，再发送普通和流式请求，使速率图
有跨周期样本。受控停止后端后健康 Gauge 仍为 1：它表示既有选路状态，
不是即时连通性；脚本暂停周期探测以触发 fallback。

结果写入 JSON（passed/failed 与逐项证据），始终停止自己创建的应用进程，
不会停止观测容器或其他应用。日志、trace 接收和指标抓取都是实际服务证据；
没有运行该脚本，就没有端到端验收结论。脚本查询 Jaeger 2.21 的 UI HTTP API，
该接口不保证跨版本兼容；升级镜像后需要重新验证。短联调不构成绩效/性能结论。

## 3. 日常查看

验收脚本结束后若要持续演示，在两个终端运行原有 mock_backend 服务，在第三
个终端启动网关：

```bash
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces \
  uv run uvicorn infergate.runtime:app --host 0.0.0.0 --port 8000 --log-config configs/logging.json
```

正常演示恢复默认健康探测；只有受控验收进程使用 3600 秒间隔。首次请求后
数据序列才出现，速率/分位数需要多次抓取；无首字节样本保持 No data，不画成 0。
仪表盘不测量 TTFT、token/s 或队列耗时。后端内部排队与模型计算仍需后端插桩，
当前 trace 只能说明网关观察到的过程。

## 4. 停止

```bash
docker compose -f observability/compose.yaml down
```

此命令保留 Prometheus/Grafana 命名卷；Jaeger 内存 trace 不保留。

配置依据：[Jaeger quick start](https://www.jaegertracing.io/docs/2.21/getting-started/)、
[Jaeger APIs](https://www.jaegertracing.io/docs/2.21/architecture/apis/)、
[Prometheus Docker installation](https://prometheus.io/docs/prometheus/latest/installation/)、
[Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)。
