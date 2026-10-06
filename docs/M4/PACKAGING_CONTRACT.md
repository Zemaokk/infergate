# M4.1 应用打包与运行配置合同

## 1. 打包边界（C 类，AI 直接实现）

- 输入：`pyproject.toml`、`uv.lock`、README、`src/` 与日志配置。
- 构建：锁文件检查与非 editable 安装；不复制宿主 `.venv`、Git、测试或验收数据。
- 输出：安装后的应用镜像，同一镜像可以通过覆盖命令运行 mock backend。
- 默认启动：单 worker Uvicorn、`infergate.runtime:app`、容器 8000 端口。
- 首次构建需要拉取基础镜像及 Python 依赖；运行时不安装依赖。
- 构建失败就停止，不重新解析锁文件绕过问题。

本轮不修改 console script，不更改流控/超时/健康转换策略，也不拆分测试依赖。
Python 基础镜像标签可漂移；完成真实构建后应记录镜像 ID、平台和基础镜像 digest。
固定依赖与镜像字节级复现是不同标准。

## 2. 运行配置（B 类，作者第一版及 review 修正已完成）

先只把两处后端地址变成可配置项，保留默认 model 与 backend ID：

| 项目 | 缺省值 | Compose 中预期值 |
| --- | --- | --- |
| `INFERGATE_BACKEND_A_URL` | `http://127.0.0.1:8001` | `http://backend-a:8000` |
| `INFERGATE_BACKEND_B_URL` | `http://127.0.0.1:8002` | `http://backend-b:8000` |

输入：创建 runtime app 时读取环境中的这两个 URL。
状态：每个 app 创建一次配置快照，路由和健康探测使用同一份 Backend 对象。
输出：保持 `mock-model`、`backend-a/backend-b`，只替换 `base_url`。
失败行为：未设置变量使用现有缺省值；显式空白、非 HTTP(S)、缺少主机的 URL
在创建 HTTP 客户端前抛出 ValueError，阻止错误配置启动，不静默回退。
URL 不包含 userinfo、query 或 fragment；不在日志/异常中回显原始 URL。
配置项作为 base URL 使用，不包含 `/v1/chat/completions` endpoint。
第一小步不接受带路径前缀的 base URL，避免尚未定义路径拼接语义。

作者先完成的最小任务：在 `runtime.py` 中读取和验证两个地址，并用它们
构造现有 routes。无需修改 router、health checker、backend client 或 endpoint。
验证可用现有 HTTPX URL 解析，不要求增加配置库。
后续真实模型名称、多后端清单、认证与模型映射在 M4.2 另定合同。

第一版之前先预测：

1. 没有设置变量时，本地启动地址应该是什么？
2. A 改成 `http://backend-a:8000` 后，推理和健康探测应分别请求哪里？
3. B 被显式设为空字符串时，应该启动、退回默认值还是报错？

共同验证：缺省行为保持原测试通过；两个自定义 URL 的探测和转发一致；
错误 URL 在客户端创建前被拒绝；创建后修改环境不改变既有 app。

## 3. 构建与验证命令

当前已验证：macOS 独立安装、Linux ARM64 镜像构建、非 root 运行、
容器网络和真实 HTTP 普通/流式请求。2026-10-06 三服务受控验收通过，
证据与未验收边界见 [ACCEPTANCE.md](ACCEPTANCE.md)。

推荐使用根目录 Compose：

```bash
docker compose up --build -d --wait
docker compose logs -f gateway
docker compose down
```

两个后端通过 `/health` healthcheck 后启动网关；网关的 `/metrics` 检查只表示
HTTP 服务可响应，不保证后端可用。依赖启动条件依据
[Docker Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/)。
Compose 配置不会因后端后来不健康而自动停止网关，运行中的路由状态仍由
现有周期健康探测更新。宿主机只开放 127.0.0.1:8000。

复现受控验收（8000 空闲，默认验收项目不存在）：

```bash
uv run python scripts/verify_m4.py --output /tmp/infergate-m4-evidence.json
```

脚本创建自己的项目，检查状态和 HTTP 行为并清理自己创建的容器/网络；
保留构建的应用镜像及构建缓存。默认不操作用户手动启动的 infergate-app 项目。
错误和成功均保存 JSON 证据；不会自动停止已占用端口的应用。

仓库根目录执行：

```bash
docker build -t infergate:m4-dev .
docker run --rm infergate:m4-dev python -c 'from infergate.runtime import app; print(type(app).__name__)'
docker run --rm -p 127.0.0.1:18001:8000 infergate:m4-dev \
  uvicorn infergate.mock_backend:app --host 0.0.0.0 --port 8000
```

在另一终端检查 mock：

```bash
curl --fail http://127.0.0.1:18001/health
curl --fail http://127.0.0.1:18001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"mock-model","messages":[{"role":"user","content":"hello"}]}'
```

前台容器通过 Ctrl-C 停止并自动移除。上述单容器命令是额外诊断入口，
本次自动验收使用三服务 Compose。网关默认 loopback URL 指向自身容器；
Compose 显式设置两个后端地址，因此不使用本地缺省值。

实现依据：[uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/)、
[Dockerfile reference](https://docs.docker.com/reference/dockerfile/)。
