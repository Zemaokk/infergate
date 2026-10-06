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

## 2. 下一步：运行配置（B 类，共同定义，作者先写关键路径）

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

## 3. 待 Docker 恢复后的验证命令

当前已验证：macOS 临时目录中按锁文件进行独立非 editable 安装，离开
源码目录后可导入 runtime/mock 入口，Uvicorn 可执行。Linux 镜像构建、
非 root 运行、容器网络及 HTTP 请求仍待实际验证。

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

前台容器通过 Ctrl-C 停止并自动移除。以上是待执行命令，当前尚未容器验证。
网关默认 loopback URL 仍指向网关容器自身；完整三服务启动需先完成第 2 节。

实现依据：[uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/)、
[Dockerfile reference](https://docs.docker.com/reference/dockerfile/)。
