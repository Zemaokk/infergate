# M4.1 应用打包验收

**状态：2026-10-06 工程检查通过，作者 teach-back 待完成。M4 整体未完成。**

## 已验证证据

- 完整 Python 测试 318 passed，2 条已有依赖弃用警告。28 项持久配置用例
  覆盖默认值、空白处理、非法 A/B 在创建客户端前拒绝、探测与普通/流式
  转发的共同地址，以及既有 app 配置冻结、新 app 重新读取环境。
- Docker Engine 29.8.2 构建并运行 Linux ARM64 应用镜像，容器 CPython
  3.13.16，UID 10001，应用加载自 site-packages，运行镜像无 /app/src。
- 三服务 Compose 实际启动且健康检查通过；网关单 worker，双后端只在
  Compose 网络内开放端口，宿主入口 127.0.0.1:8000。
- scripts/verify_m4.py 完成 11 个真实 HTTP 业务请求：四次轮换 A/B/A/B；
  SSE 正文一致，首块与 [DONE] 分开到达；A 停止且探测更新后连续三次到 B；
  A 恢复且探测更新后重新轮换；双后端停止且探测更新后返回
  503 no_backend_available。最终 active_requests=0。
- JSON 保存 11 条完成日志、健康状态变化、客户端分块到达时刻、安装路径、
  镜像信息与清理状态。临时验收容器/网络全部删除，保留应用镜像和构建缓存。
- Compose config、脚本 CLI 和 `git diff --check` 通过。

原始证据：[packaging-2026-10-06.json](evidence/packaging-2026-10-06.json)。
脚本运行于北京时间 2026-10-06 14:19；JSON 时间使用 UTC。
本次应用镜像 ID：
`sha256:0a941375a2b1db5fac43e42443a098cbcab6fed3984cf93260d4874578fbdbb3`。
初次构建解析的 Python manifest digest 为
`sha256:2b6e177adb67a564bba97e6f0eab8760a7dc3645582d70277a055a4327a737e5`，
uv digest 为 `sha256:069a51314a7bb6031777a9273205fe1b0b19e914ef418207d1338b268df641dd`。
Dockerfile 仍使用标签，不承诺未来构建的字节级一致。

## 当前边界

这是 mock 集成检查，无真实模型、GPU、性能或 Linux AMD64 验证。
本次不联调 M3 的 Prometheus/Jaeger/Grafana 容器，不开启 OTLP exporter。
服务启动健康检查和 runtime 后端路由健康状态是不同的观测。
本次等探测更新后验证路由，不确定性触发探测前 fallback；原有 M2 证据仍适用。
单进程配额、first-byte 非 TTFT、无等待队列等既有边界保持。

## 作者复述（待完成）

1. 为什么 Compose 使用 backend-a:8000，而不是 127.0.0.1:8001？
2. 修改环境变量后，为什么已有 app 不会自动切换地址？
3. 网关容器健康，但两个后端已停止，业务请求可能返回什么？

作者主导运行配置读取和校验；AI 协助 focused review、持久测试、容器验收
及文档。完成上述复述后再收尾 M4.1，讨论 M4.2 实际可用后端与模型。
