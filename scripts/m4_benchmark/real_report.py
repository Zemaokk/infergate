"""Render formal native-model evidence with protocol-specific comparisons."""

import argparse
import hashlib
import json
import os
import statistics
from pathlib import Path


def token_summary(rows, protocol):
    key = "completion_tokens" if protocol == "chat" else "output_tokens"
    values = [(r.get("usage") or {}).get(key) for r in rows if r["valid_response"]]
    valid = [n for n in values if isinstance(n, int) and not isinstance(n, bool) and n >= 0]
    return {"samples": len(valid), "missing": len(values) - len(valid),
            "min": min(valid) if valid else None, "max": max(valid) if valid else None,
            "mean": statistics.mean(valid) if valid else None}


def render(evidence, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    summary = json.loads((evidence / "summary.json").read_text())
    manifest = json.loads((evidence / "manifest.json").read_text())
    rows = [json.loads(line) for line in (evidence / "requests.jsonl").read_text().splitlines()]
    if (manifest["profile"] != "real" or manifest["outcome"] != "passed"
            or manifest["source_changed_during_run"] or not summary["all_valid"]):
        raise ValueError("Formal unchanged real-model evidence must pass before reporting")
    if len(rows) != 1200 or len(summary["cases"]) != 24:
        raise ValueError("Expected 24 cases and 1,200 measured attempts")
    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "svg.fonttype": "none"})
    colors = {"direct": "#607D8B", "gateway": "#1769AA"}
    aggregate = summary["aggregate"]
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), layout="constrained")
    for index, protocol in enumerate(("chat", "responses")):
        protocol_rows = [r for r in aggregate if r["group"] == f"real-{protocol}"]
        for column, metric, scale, ylabel in (
            (0, "success_rps", 1, "Successful requests / second"),
            (1, "success_p95_seconds", 1000, "Successful request p95 (ms)")):
            ax = axes[index, column]
            for target_index, target in enumerate(("direct", "gateway")):
                selected = sorted((r for r in protocol_rows if r["target"] == target), key=lambda r: r["concurrency"])
                medians = [r[metric]["median"] * scale for r in selected]
                error = [[(r[metric]["median"] - r[metric]["min"]) * scale for r in selected],
                         [(r[metric]["max"] - r[metric]["median"]) * scale for r in selected]]
                positions = [i + (-.16 if target_index == 0 else .16) for i in range(len(selected))]
                ax.bar(positions, medians, width=.3, yerr=error, capsize=4,
                       label=target, color=colors[target])
            maximum = max(r[metric]["max"] * scale for r in protocol_rows)
            ax.set(xlabel="Closed-loop client concurrency", ylabel=ylabel,
                   xticks=[0, 1], xticklabels=[1, 2], ylim=(0, maximum * 1.1), title=protocol)
            ax.grid(axis="y", alpha=.2)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=2, frameon=False)
    fig.suptitle("Qwen2.5-7B-Instruct / RTX4090 / vLLM 0.10.1\n"
                 "Repeated warm prompt; 64-token budget; median and range of 3 rounds", fontsize=12)
    for extension in ("png", "svg"):
        fig.savefig(output / f"real-comparison.{extension}", dpi=180)
    plt.close(fig)

    lines = ["# M4.4 真实模型 benchmark", "",
             "本报告比较同一原生协议的直连与网关；两种协议分别统计。", "",
             f"- 开始：{manifest['started_utc']}；结束：{manifest['finished_utc']}。",
             "- 24 个 case，1,200 次测量请求；每 case 50 次，预热 5 次，重复三轮。",
             f"- 有效成功：{sum(r['valid_response'] for r in rows)}/{len(rows)}。",
             "- 请求、网关、模型都在 GPU 主机，通过 loopback；SSH 不在请求路径。", "",
             "## 环境及工作负载", "",
             f"- GPU：{manifest['environment']['gpu']}。",
             "- Qwen2.5-7B-Instruct；vLLM 0.10.1+cu118 / PyTorch 2.7.1+cu118。",
             "- V1、BF16、上下文 4096、max_num_seqs=2、显存比例 0.85、eager。",
             "- prefix caching 和 chunked prefill 开启，重复相同 prompt，结果属于预热条件。",
             "- 网关单 worker、单后端、全局容量 2；固定合法 key 的实验额度提高至 100,000，避免 key 配额干扰。",
             "- 保留健康探测、完成日志、metrics 和 trace 埋点；不导出 OTLP。",
             "- Chat temperature=0；Responses 使用后端默认 temperature=0.7。其他默认参数见环境证据。",
             "- 两协议均为 64-token 输出上限；Responses 显式 store=false。", "",
             "模型快照的下载 revision 未记录，配置哈希和权重文件大小已保存；不声称权重逐字节版本已核验。", "",
             "## 成功吞吐与成功延迟", "",
             "数值为三轮中位值，方括号为最小值至最大值，不是置信区间。", "",
             "| 协议 | 并发 | 入口 | 成功 req/s [范围] | 成功 p50 ms | 成功 p95 ms [范围] |",
             "| --- | --- | --- | --- | --- | --- |"]
    for result in sorted(aggregate, key=lambda r: (r["group"], r["concurrency"], r["target"])):
        throughput, p95 = result["success_rps"], result["success_p95_seconds"]
        lines.append(f"| {result['group'].removeprefix('real-')} | {result['concurrency']} | {result['target']} | "
                     f"{throughput['median']:.3f} [{throughput['min']:.3f}, {throughput['max']:.3f}] | "
                     f"{result['success_p50_seconds']['median']*1000:.2f} | "
                     f"{p95['median']*1000:.2f} [{p95['min']*1000:.2f}, {p95['max']*1000:.2f}] |")
    lines += ["", "![真实模型对照](real-comparison.png)", "", "## 输出与验收", "",
              "| 协议 | 入口 | usage 有效样本 | 缺失 | 输出 token 均值 | 范围 |",
              "| --- | --- | --- | --- | --- | --- |"]
    token_stats = []
    for protocol in ("chat", "responses"):
        for target in ("direct", "gateway"):
            data = [r for r in rows if r["protocol"] == protocol and r["target"] == target]
            stats = token_summary(data, protocol)
            token_stats.append({"protocol": protocol, "target": target, **stats})
            mean = f"{stats['mean']:.2f}" if stats["mean"] is not None else "未提供"
            lines.append(f"| {protocol} | {target} | {stats['samples']} | {stats['missing']} | "
                         f"{mean} | {stats['min']}–{stats['max']} |")
    lines += ["", "成功要求 HTTP 200、正确协议/模型及非空文本；Responses 要求内部状态 completed。",
              "Chat 的 finish_reason=length 也属于本次预算下的成功请求；文本可能截断。",
              "所有测量网关请求的完成日志均按 trace ID 匹配，route 正确、attempt_count=1、",
              "outcome=completed、cleanup_failed=false；每 case 结束后网关健康且 active=0。", "",
              "## 解释边界", "", "此结果覆盖短输入、固定输出上限、热 prefix cache 和并发 1/2。",
              "单轮 50 样本的 p95 为探索性指标，不是生产 SLA。直连/网关分位数的差不能",
              "当作每请求纯代理耗时；应结合三轮波动和输出 token 数判断。",
              "Responses 含随机采样，不能把两种协议的延迟差解释为协议固有开销。",
              "未测量冷 cache、长输入、流式首内容延迟、故障注入或超过容量的 GPU 性能。",
              "Mac 上的 mock 实验与 Linux 上的真实推理使用不同硬件和后端，不能直接横向比较绝对吞吐或延迟。", "",
              "## 证据", "", f"本地原始证据：`{evidence.resolve()}`。", "",
              "正式目录包含 manifest、实际源码快照、逐请求响应/usage、预热、各 case 汇总和网关日志。",
              "上层证据目录还保存环境、模型启动日志、两次小样本与最终清理记录。",
              "首次小样本因工具错误要求日志 outcome=success",
              "而失败；实际生成成功且网关记录 completed。修正工具并补回归后，小样本再次通过。",
              "首次及修正后的小样本均单独保留，不计入正式性能汇总。", ""]
    archive = output.parent / "evidence" / f"benchmark-real-{manifest['started_utc'][:10]}.tar.gz"
    if archive.exists():
        relative = os.path.relpath(archive, output)
        lines += [f"可随仓库保存的 [完整压缩证据]({relative})，包含上述原始记录与失败小样本。", "",
                  f"SHA256：`{hashlib.sha256(archive.read_bytes()).hexdigest()}`。", ""]
    (output / "RESULTS.md").write_text("\n".join(lines))
    provenance = {"matplotlib": matplotlib.__version__, "token_stats": token_stats,
                  "summary_sha256": hashlib.sha256((evidence / "summary.json").read_bytes()).hexdigest(),
                  "manifest_sha256": hashlib.sha256((evidence / "manifest.json").read_bytes()).hexdigest()}
    (output / "report-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render(args.evidence.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
