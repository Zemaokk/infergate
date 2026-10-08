# Redraw saved benchmarks

This procedure uses the recorded archives and needs no GPU. Run from the
repository root. Use fresh extraction, environment, and output directories.

Verify the two portable archives first. Use `shasum` on macOS or `sha256sum`
on Linux:

```sh
(cd docs/archive/2026-10-08 && shasum -a 256 -c docs/M4/evidence/SHA256SUMS)
```

Use a clean checkout without these existing evidence directories. The temporary
plotting environment and report output directories below should also be fresh;
choose new paths when repeating the procedure.

```sh
mkdir -p artifacts/m4-benchmark/remote-20261007
tar -xzf docs/archive/2026-10-08/docs/M4/evidence/benchmark-local-2026-10-07.tar.gz -C artifacts/m4-benchmark
tar -xzf docs/archive/2026-10-08/docs/M4/evidence/benchmark-real-2026-10-07.tar.gz -C artifacts/m4-benchmark/remote-20261007
uv venv --python 3.13 /tmp/infergate-plot
uv pip install --python /tmp/infergate-plot/bin/python matplotlib==3.11.2
MPLCONFIGDIR=/tmp/infergate-mpl /tmp/infergate-plot/bin/python -m scripts.m4_benchmark.report artifacts/m4-benchmark/20261007-local-retry-01 --output /tmp/infergate-local-report
MPLCONFIGDIR=/tmp/infergate-mpl /tmp/infergate-plot/bin/python -m scripts.m4_benchmark.real_report artifacts/m4-benchmark/remote-20261007/real-01 --output /tmp/infergate-real-report
```

Plotting dependencies stay separate from the gateway environment. Reports
contain Markdown, PNG/SVG, and input hashes. The local archive includes both
original and replacement cases; preserve both directories. The real archive also
includes two pilots, environment records, startup logs, and cleanup evidence.

Absolute paths and source snapshots in historical manifests describe the
original machine. They are not paths to reuse on a new machine. The original
local report's statement that real-model measurements were still pending is a
dated snapshot; the subsequent [real-model report](../archive/2026-10-08/docs/M4/benchmark-real-20261007/RESULTS.md)
is separate.


Generated report evidence links are relative to the output layout. The temporary
outputs below the system's temporary directory are for inspecting plots and
numbers; use the [validation index](../reference/validation.md) to navigate the
checked-in evidence. Plot bytes can vary with fonts and platform even when the
input hashes and numerical summaries agree.
