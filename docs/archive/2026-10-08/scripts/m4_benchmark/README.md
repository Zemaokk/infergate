# M4 本地 benchmark 工具

工程配套工具，不属于已安装的生产 runtime。设计见
[设计合同](../../docs/M4/BENCHMARK_CONTRACT.md)。从仓库根目录运行：

```sh
.venv/bin/python -m scripts.m4_benchmark.run --profile pilot --output artifacts/m4-benchmark/pilot-01
.venv/bin/python -m scripts.m4_benchmark.run --profile local --output artifacts/m4-benchmark/local-01
```

- `pilot`：一轮，开销每 case 40 次、预热 5 次，额度实验 4 秒、并发每档 3 波。
  仅核对采集和行为，不用于性能结论。
- `local`：正式三轮，开销每 case 1,000 次、预热 50 次；额度每 case 30 秒，
  每档并发 100 波。通常需约 12–15 分钟。
- 只启动 loopback 临时服务，监听 socket 由父进程预留并传给子进程，退出时
  清理自己创建的服务。不访问远程 GPU，不修改生产的配额默认值。
- 需要本机允许监听 loopback。输出目录必须不存在，避免覆盖既有证据。
  原始输出默认在 `.gitignore` 中，需自行备份，不能把它误认为已提交证据。
- 完成日志通过客户端生成的 trace ID 逐条匹配；拒绝尝试次数为 0，mock 的
  业务请求增量必须等于有效成功数，每个 case 结束后 active 必须归零。
- quota/order 实验使用只记录实际判定时刻与余量的 limiter 子类，不重写算法；
  开销实验使用原 limiter，避免审计采集污染基线。
- 429、503、客户端异常和无效 200 均保留；缺日志、漏发/迟发超过 100 ms、
  非预期错误或容量未释放会标记 case 无效，并返回非零退出码。
- `manifest.json` 保存源码哈希，`sources/` 保存实际源码与配置。运行中不要
  修改被测源码；变化会被标记，运行返回非零。预热失败时服务日志仍保留。

生成正式本地图表与 Markdown 报告（使用单独安装了 matplotlib 的 Python）：

```sh
python -m scripts.m4_benchmark.report artifacts/m4-benchmark/local-01 --output docs/M4/benchmark-local
```

matplotlib 只用于报告，不加入网关运行依赖。报告保存绘图库版本与证据哈希，
图中误差线是三轮范围，不是置信区间。正式测量时避免另外运行高负载任务。

如果正式运行因漏发等原因产生无效 case，可按原参数定向补测：

```sh
.venv/bin/python -m scripts.m4_benchmark.retry artifacts/m4-benchmark/local-01 --output artifacts/m4-benchmark/local-retry-01
```

补测工具只选择无效 case，拒绝挑选有效但较慢的轮次；要求被测源码与原运行
一致。合并 summary 显式保留被排除的原 case、原因及补测对应关系。
生成报告时指向补测目录，且必须同时备份原运行与补测目录。补测再次无效时
仍返回非零，不自动反复尝试直到得到较好结果。

## 真实模型

先在 GPU 主机核对模型服务健康、原生 Chat/Responses 路由、网关安装源码哈希，
并记录实际推理参数、生成配置和 GPU 环境。`--environment` 指向这次实时核对
得到的 JSON，不要直接复用旧机器或旧进程的环境记录。M4.4 的实际环境记录在
远程 `/root/infergate-m44/environment.json`；模型服务与采集客户端都在该主机。

```sh
.venv/bin/python -m scripts.m4_benchmark.real --profile pilot --environment /root/infergate-m44/environment.json --output /root/infergate-m44/pilot-02
.venv/bin/python -m scripts.m4_benchmark.real --profile real --environment /root/infergate-m44/environment.json --output /root/infergate-m44/real-01
```

只接受 `http://127.0.0.1:端口` 后端，禁止无意中从 Mac 经公网进行性能测量。
采集器创建临时单 worker 网关，保留健康检查与观测，关闭 OTLP 导出；全局
容量 2、key 大额度。Chat 使用 temperature=0，Responses 保留后端默认采样，
分别做直连/网关对照，不能据两协议延迟差断言协议本身更快。

正式 profile：两协议 × 两入口 × 并发 1/2 × 三轮，每 case 50 次、预热 5 次。
成功 Chat 允许 stop/length；成功 Responses 要求 completed 与非空 output_text，
不要求响应回显 store。逐请求保存原生响应与 usage，结束/取消时及时落盘。
失败立即结束正式运行，保留证据；不得修改正在测量的远程源码。

将证据下载回本机后，在独立 matplotlib 环境生成正式图表：

```sh
python -m scripts.m4_benchmark.real_report artifacts/m4-benchmark/remote-20261007/real-01 --output docs/M4/benchmark-real-20261007
```

报告要求完整 24 个 case、1,200 条原始测量记录，且正式 run 成功、源码未变。
模型下载 revision 若没有原始记录，应保留未知；配置哈希和权重文件大小不能
等价替代全部权重逐字节校验。报告同时说明热 cache、64-token 上限、单轮
尾延迟样本有限以及 HTTP 请求成功不保证文本没有截断。
