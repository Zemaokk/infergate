# M2 工作计划：负载保护与公平性

**状态：** 已启动，合同与作者预测阶段；尚未实现或验收 M2 功能  
**模式：** Learning mode  
**基线：** M1 已验收；2026-09-24 当前检出版本 `pytest -q` 为 51 passed

M2 的范围及完成标准以 [项目蓝图](../PROJECT_PLAN.md) 和
[人机协作约定](../COLLABORATION_CONTRACT.md) 为准。M1 的请求转发、健康检查和
流式资源清理行为是必须保持的基线。

## 1. 最小范围与顺序

1. **M2.1 Per-key token bucket（A 类，作者先写）：** 定义 key 来源、桶状态、
   补充规则、扣费时机和拒绝行为。先写预测和最小实现，再做 focused review。
2. **M2.2 全局并发上限与 backpressure（A 类，作者先写）：** 同时保护普通请求和
   流式请求。第一版建议容量满时立即拒绝，即等待队列容量为 0；这是蓝图允许的
   “明确的快速拒绝策略”。如果选择有界等待，先另定最大队列长度、等待期限和
   取消时的清理规则。
3. **M2.3 Retry / fallback policy（A 类，作者先写条件判断）：** 先列出允许重试
   的失败类型、次数和 backend 排除规则，再实现；流式响应一旦提交，不透明重试。
4. **M2.4 集成与验收（B 类，双方完成）：** 验证限制能跨请求生效，资源在正常、
   错误和取消路径释放；保留 M0/M1 回归测试。AI 可补 fixtures 和重复样板（C 类）。

每项核心任务依次经过 contract、作者预测、作者第一版、AI focused review、
验证、teach-back、记录。进入下一项前，当前项须有可运行的测试证据。

## 2. 请求路径与生命周期边界

```text
validate request
  -> identify caller / check rate limit
  -> acquire global capacity or reject
  -> select healthy backend
  -> forward, with only explicitly allowed retry/fallback
  -> release capacity when non-streaming response finishes,
     or when streaming body finishes/fails/is cancelled/disconnected
```

顺序是待确认的设计选择。无论顺序如何，必须避免：拒绝后的请求仍选择或调用
backend；等待或重试无限增长；流式 endpoint 返回 `StreamingResponse` 时过早释放
并发名额；失败或取消后遗漏释放。限流、并发和重试的上限均按单个 gateway 进程
定义；多进程共享配额不在第一版范围内。

## 3. M2.1 作者任务

2026-09-26 进度：作者提出 `dict[key, bucket]` 状态结构，并正确预测示例中的
“通过、通过、拒绝、拒绝”；确认以 `X-InferGate-Key` 标识调用方，缺失或空值
直接拒绝。并发更新边界、首次实现及其测试尚未完成。

先阅读 [M2.1 行为合同草案](RATE_LIMIT_CONTRACT.md)，然后用自然语言或伪代码
回答以下四项，再写最小实现：

1. **输入：** 请求以什么 header 或其他字段识别调用方？缺失或空值怎样处理？
2. **状态：** 每个 key 的令牌数和上次补充时间存在哪里？并发请求怎样安全更新？
3. **输出：** 何时扣除一个令牌？成功和拒绝分别返回什么？
4. **失败：** 桶已空、时钟向后变化、请求取消时分别怎样处理？

请再预测一个小例子：容量为 2、初始有 2 个令牌、每秒补充 1 个令牌；同一 key
在 `t=0` 连续发送 3 次，`t=0.5` 再发送 1 次，分别会接受还是拒绝？另一个
key 的第一请求应发生什么？说明你选择的边界规则。

AI 下一步仅对你的预测或第一版指出最关键的一个可验证问题，并补框架细节；
不会默认代写 token bucket 的完整实现。

建议提交信息（完成 M2.1 实现与验证后使用）：
`Implement per-key token bucket admission control`

## 4. M2 完成标准

- 同一 key 的超额请求会以确定状态码被拒绝，其他 key 的配额不受影响；
- 达到全局容量上限时立即拒绝或在明确定义的有界队列中等待；
- 普通和流式请求在所有退出路径都释放容量，流式会一直占用到实际结束；
- retry / fallback 只在已批准的失败条件下发生，并有硬性次数上限；
- M0/M1 回归测试通过，另有并发、限流和失败路径测试；
- 作者能解释状态位置、更新时机、一个失败场景及新测试的预期结果。

M2 暂不包含分布式配额、复杂排队调度、token-aware scheduling 或性能结论。
