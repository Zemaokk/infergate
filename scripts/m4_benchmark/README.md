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
