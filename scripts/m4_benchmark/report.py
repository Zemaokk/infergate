"""Render retained local evidence; requires matplotlib only in the plotting environment."""

import argparse
import hashlib
import json
from pathlib import Path


def render(evidence: Path, output: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    summary = json.loads((evidence / "summary.json").read_text())
    manifest = json.loads((evidence / "manifest.json").read_text())
    if not summary["all_valid"] or manifest["outcome"] != "passed" or manifest["source_changed_during_run"]:
        raise ValueError("Run is not valid; inspect evidence before making a performance report")
    if manifest["profile"] != "local":
        raise ValueError("Pilot results validate tooling; they are not the formal performance report")
    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "svg.fonttype": "none"})
    colors = {"direct": "#607D8B", "gateway": "#1769AA"}
    aggregate = summary["aggregate"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), layout="constrained")
    for target in ("direct", "gateway"):
        rows = sorted((r for r in aggregate if r["group"] == "overhead" and r["target"] == target),
                      key=lambda r: r["concurrency"])
        for ax, metric, scale, ylabel in (
            (axes[0], "success_rps", 1, "Successful requests / second"),
            (axes[1], "success_p95_seconds", 1000, "Successful request p95 (ms)")):
            medians = [r[metric]["median"] * scale for r in rows]
            errors = [[(r[metric]["median"] - r[metric]["min"]) * scale for r in rows],
                      [(r[metric]["max"] - r[metric]["median"]) * scale for r in rows]]
            ax.errorbar([r["concurrency"] for r in rows], medians, yerr=errors,
                        fmt="o-", capsize=4, color=colors[target], label=target)
            ax.set(xlabel="Closed-loop client concurrency", ylabel=ylabel, xticks=[1, 2, 4, 8])
            ax.set_ylim(bottom=0)
            ax.grid(axis="y", alpha=.2)
            ax.legend(frameon=False)
    # Fix limits after both series; setting the lower limit inside the loop disables autoscaling.
    for ax, metric, scale in ((axes[0], "success_rps", 1), (axes[1], "success_p95_seconds", 1000)):
        highest = max(r[metric]["max"] * scale for r in aggregate if r["group"] == "overhead")
        ax.set_ylim(0, highest * 1.1)
    fig.suptitle("Local HTTP mock: median and full range of 3 rounds\n"
                 "1,000 attempts per case; gateway limit 32; key quota nonbinding", fontsize=11)
    for extension in ("png", "svg"):
        fig.savefig(output / f"overhead.{extension}", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), layout="constrained")
    wave_rows = sorted((r for r in aggregate if r["group"] == "waves"), key=lambda r: r["concurrency"])
    rate_rows = sorted((r for r in aggregate if r["group"] == "rate" and r["keys"] == 1), key=lambda r: r["rate"])
    for ax, rows, xkey, xlabel, title in (
        (axes[0], wave_rows, "concurrency", "Simultaneous requests per wave", "Global capacity 2; mock delay 200 ms"),
        (axes[1], rate_rows, "rate", "Planned requests / second (one key)", "Bucket capacity 2; refill 1/s; 30 s")):
        x = list(range(len(rows)))
        accepted = [r["success_rate"]["median"] * 100 for r in rows]
        ax.bar(x, accepted, color="#1769AA", label="valid success")
        ax.bar(x, [100 - value for value in accepted], bottom=accepted,
               color="#E8A23A", label="expected rejection")
        ax.set(xticks=x, xticklabels=[r[xkey] for r in rows], xlabel=xlabel,
               ylabel="Issued requests (%)", ylim=(0, 105), title=title)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=2, frameon=False)
    fig.suptitle("Local protection experiments: median proportions across 3 rounds", fontsize=11)
    for extension in ("png", "svg"):
        fig.savefig(output / f"protection.{extension}", dpi=180)
    plt.close(fig)

    lines = ["# M4.4 本地受控实验结果", "", "本结果只适用于本机 HTTP mock，不能代表 GPU 推理性能。", "",
             f"- 平台：`{manifest['platform']}`；Python `{manifest['python'].split()[0]}`。",
             f"- 开始：{manifest.get('original_started_utc', manifest['started_utc'])}；结束：{manifest['finished_utc']}。",
             f"- {len(summary['cases'])} 个有效 case 通过行为及证据核对（补测情况见下文）。",
             "- 数值为三轮中位值；方括号为三轮最小值至最大值，不是置信区间。", "",
             "## 网关开销", "", "每个入口/并发/轮次 1,000 次尝试，成功率均需单独核对。", "",
             "| 并发 | 入口 | 成功率 | 成功 req/s [范围] | 成功 p95 ms [范围] |",
             "| --- | --- | --- | --- | --- |"]
    for row in sorted((r for r in aggregate if r["group"] == "overhead"),
                      key=lambda r: (r["concurrency"], r["target"])):
        throughput, p95 = row["success_rps"], row["success_p95_seconds"]
        lines.append(f"| {row['concurrency']} | {row['target']} | {row['success_rate']['median']:.1%} | "
                     f"{throughput['median']:.1f} [{throughput['min']:.1f}, {throughput['max']:.1f}] | "
                     f"{p95['median']*1000:.2f} [{p95['min']*1000:.2f}, {p95['max']*1000:.2f}] |")
    excluded = summary.get("excluded_invalid_cases", [])
    if excluded:
        lines += ["", "原始运行有以下无效 case；它们的全部记录保留，因预先定义的有效性规则",
                  "排除出性能汇总，并按相同参数补测。不是从有效轮次中挑选较快结果：", ""]
        for case in excluded:
            lines.append(f"- `{case['case']}`：{'; '.join(case['issues'])}；"
                         f"已发 {case['issued']}，漏发 {case.get('missed', 0)}。")
        lines += ["", f"原始证据目录：`{summary['original_evidence']}`。", "",
                  f"原始运行起点：{manifest['original_started_utc']}；本报告结束时间含补测。"]
    lines += ["", "![成功吞吐与成功延迟](overhead.png)", "", "## 流量保护", "",
              "| 实验 | 负载 | key 数 | 成功率中位值 | 预期拒绝 |", "| --- | --- | --- | --- | --- |"]
    for row in aggregate:
        if row["group"] not in ("rate", "waves"):
            continue
        load = (f"每波 {row['concurrency']} 个" if row["group"] == "waves" else f"每 key {row['rate']} req/s")
        lines.append(f"| {row['group']} | {load} | {row['keys']} | "
                     f"{row['success_rate']['median']:.2%} | "
                     f"{'503 concurrency_limit_exceeded' if row['group'] == 'waves' else '429 rate_limit_exceeded'} |")
    lines += ["", "![接纳与拒绝比例](protection.png)", "",
              "顺序验收另行验证：目标 key 得到并发 503、并发 503、key 429；拒绝尝试次数均为 0。",
              "全部波次结束后 active=0，恢复请求成功；实际服务端额度时刻与 refill 规则及 HTTP 结果一致。", "",
              "## 解释边界", "", "该机器同时承担客户端、网关与后端，包含客户端调度、连接复用、HTTP、",
              "日志和观测开销。零延迟 mock 对操作系统调度及后台活动敏感；三轮范围",
              "可能较宽。端到端 p95 差异不能解释为每个请求的纯网关耗时，",
              "也不能从某档吞吐直接外推生产容量。尚未获得真实模型性能数据。", "",
              "## 原始证据", "", f"证据目录：`{evidence.resolve()}`。", "",
              "包含 manifest、源码快照、逐次 requests.jsonl、missed.jsonl、逐 case JSON、",
              "服务日志和 summary.json。预热排除；波次恢复请求单列；固定到达率的",
              "吞吐窗口包含完整计划发送窗口及超出窗口的排空时间。补测报告需同时保留",
              "原始证据目录与补测目录；合并汇总不复制原始请求和日志。", ""]
    (output / "RESULTS.md").write_text("\n".join(lines))
    provenance = {"plotting_matplotlib": matplotlib.__version__,
                  "source_summary_sha256": hashlib.sha256((evidence / "summary.json").read_bytes()).hexdigest(),
                  "source_manifest_sha256": hashlib.sha256((evidence / "manifest.json").read_bytes()).hexdigest()}
    (output / "report-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render(args.evidence, args.output)


if __name__ == "__main__":
    main()
