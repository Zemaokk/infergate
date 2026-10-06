# M4.3 原生 Responses 验收

**2026-10-06：受控测试、真实后端验收与作者额度顺序复述完成，M4.3 收尾。**
本阶段验证同协议转发与共享控制，不是 benchmark 或完整 OpenAI API 兼容认证。

## 实现与测试

作者完成共享执行路径抽取、route 观测和 Responses endpoint 第一版及 review
修正；作者授权 AI 统一请求模型校验的严格程度。两个入口共用同一个 router、
key limiter、concurrency limiter、backend client 与观测生命周期。响应沿
原生协议透传，不把 Responses 请求转成 Chat 请求。

模型测试 47 项、route 新增测试 4 项、实际 HTTP endpoint 测试 18 项；
完整测试集 **405 passed**，2 条已有依赖弃用警告。HTTP 测试覆盖正文/path/
响应透传、错误顺序、跨入口额度、Chat 流占满容量时 Responses 的 503 与
零次后端尝试、无后端/连接错误/fallback/取消后释放容量。

作者复述非法正文在进入 endpoint 前被拒绝，而并发拒绝仍受 key 限流；
AI 补充准确顺序：正文→key→扣额度→全局并发→路由/后端。额度是否消耗
由执行顺序决定，不能仅依据有没有后端尝试判断。

## 真实环境

| 项目 | 实际验证 |
| --- | --- |
| GPU / 驱动 | RTX4090 24 GB / 550.54.14 |
| 推理目录 | `/root/infergate-m43/vllm-env`，独立于 M4.2 |
| 推理版本 | vLLM 0.10.1+cu118、PyTorch 2.7.1+cu118、CUDA 11.8 |
| 兼容依赖 | Transformers 4.55.2、OpenAI SDK 1.99.1 |
| 推理 Python | 3.12.3；GPU BF16 矩阵计算通过 |
| 模型 | 复用 Qwen2.5-7B-Instruct 已下载权重 |
| 启动参数 | V1、BF16、上下文 4096、max_num_seqs=2、显存占比 0.85、eager |
| 验收端口 | 后端 127.0.0.1:8002、独立网关 127.0.0.1:8003 |
| 网关 | Python 3.13.14，复制原已验证依赖后非 editable 安装当前项目 |

官方构建来源：[vLLM 0.10.1 release](https://github.com/vllm-project/vllm/releases/tag/v0.10.1)。
原生接口由 [该版本源码](https://github.com/vllm-project/vllm/blob/v0.10.1/vllm/entrypoints/openai/api_server.py)
与实际 OpenAPI、真实生成共同确认。官方 wheel 本地下载后通过 SSH 传输，
两端 SHA256 一致：`3f570ca43613b45c8f0631dddf5a7791f30f97c796847d5a66a4f21350ba543d`。

通用依赖优先清华镜像；固定 cu118 的 torch/torchaudio/torchvision 使用官方
PyTorch 索引。首次镜像优先级导致大型通用依赖下载慢，调整后安装完成。
初始无上限解析得到 Transformers 5.18.0、OpenAI 3.24.0；运行前固定为上表
版本并通过 uv pip check。完整依赖及源码/锁文件 SHA256 见
[环境证据](evidence/responses-environment-2026-10-06.json)。实际安装源码、上传源码
和本地源码哈希一致；macOS 归档元数据不参与源码哈希比较。

## 实际 HTTP 结果

先直接请求后端，再顺序发送七个专用网关业务请求：

| 场景 | HTTP | 网关尝试次数 | 结果 |
| --- | --- | ---: | --- |
| 直接原生 Responses | 200 | 不经过网关 | 原生 response、非空 output_text |
| 网关最小 Responses | 200 | 1 | 正确模型、非空生成 |
| 显式 instructions=null、stream=false、background=false | 200 | 1 | 后端接受，原生 response |
| store=true | 400 | 0 | invalid_request_body |
| stream=true | 400 | 0 | invalid_request_body |
| input 全空白 | 400 | 0 | invalid_request_body |
| previous_response_id 未支持字段 | 400 | 0 | invalid_request_body |
| 新后端上的 Chat 普通请求回归 | 200 | 1 | 非空 choices 文本 |

完成日志与七个网关请求一一对应，route 正确；所有 cleanup_failed=false，
非流式 first_byte_sec=null；请求指标区分两个入口，最终 active_requests=0。
证据见 [真实成功记录](evidence/responses-2026-10-06.json)。

请求均显式 store=false，后端响应 JSON 不含 store 字段，网关未补字段。
首次工具错误期待必须回显 store，在直接生成成功后报 KeyError；按合同修正
检查后重跑通过，保留 [首次失败记录](evidence/responses-first-attempt-2026-10-06.json)。
这不证明完整状态管理、检索或持久化保证。生成上限 64 tokens，文本可能截断；
本次内部 status 为 completed，但不把 HTTP 完成等同于任意模型完整生成。

## 服务恢复与复现

临时后端及网关均已停止；原 M4.2 模型恢复为 PID 8951，原网关部署未覆盖。
恢复后直接 Chat 普通与 SSE/[DONE]、原 8000 网关普通请求均通过，最终
active_requests=0，8002/8003 不再监听。见
[恢复检查](evidence/responses-restoration-2026-10-06.json)及
[恢复后的普通/SSE 请求](evidence/responses-restored-chat-2026-10-06.json)。PID 为验收快照。

复现文件：configs/m4/vllm-responses-requirements.txt、scripts/start_m43_backend.sh、
scripts/start_m43_gateway.sh、scripts/verify_real_responses.py。独立环境保留。
运行新版模型前需先核对并停止当前模型，避免两套 7B 服务竞争同一张卡的显存。
启动脚本前台执行，验收脚本要求专用网关本轮无其他业务流量：

```bash
bash /root/infergate-m43/gateway/scripts/start_m43_backend.sh
# 另一个终端启动专用网关，再在第三个终端验收。
bash /root/infergate-m43/gateway/scripts/start_m43_gateway.sh \
  >> /root/infergate-m43/gateway.log 2>&1
# 等待模型 /health 为 200，网关 backend-a 健康指标为 1 后再验收。
/root/infergate-m43/gateway/.venv/bin/python \
  /root/infergate-m43/gateway/scripts/verify_real_responses.py \
  --gateway-log /root/infergate-m43/gateway.log \
  --output /root/infergate-m43/responses-evidence.json
```

上例日志重定向至 gateway.log；自行前台显示日志时可省略 --gateway-log，
但那次运行不会验证完成日志。重复验收需重启专用网关以清空指标计数。
原 8000 仍是 M4.2 部署，不能据此调用新版 Responses；本仓库当前代码及
独立 M4.3 部署才包含该入口。未开展吞吐/延迟实验，下一阶段是 M4.4 workload 设计。
