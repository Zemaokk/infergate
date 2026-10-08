# Collect local benchmarks

This procedure measures controlled mock HTTP behavior on the local machine.
It does not measure GPU inference. Use an installed Python 3.13 checkout, free
loopback sockets, stable machine load, and fresh output directories.

## Run a pilot, then the formal profile

```sh
uv run --no-sync python -m scripts.m4_benchmark.run --profile pilot --output artifacts/m4-benchmark/new-pilot
```

Read `manifest.json`, `summary.json`, and the service logs. Require a passing
pilot before continuing:

```sh
uv run --no-sync python -m scripts.m4_benchmark.run --profile local --output artifacts/m4-benchmark/new-local
```

The tool reserves loopback sockets, launches temporary services, and cleans up
its processes on normal or failed exit. It refuses existing output directories.
Do not edit measured sources while it runs. Raw artifacts are ignored by Git;
back them up explicitly. Formal runs previously took about 12–15 minutes, but
elapsed time depends on the machine.

## Handle an invalid case

Read the saved issues before deciding to repeat anything. A failed arrival
schedule is invalid; a valid slow result is still a result. With unchanged
measured sources, use:

```sh
uv run --no-sync python -m scripts.m4_benchmark.retry artifacts/m4-benchmark/new-local --output artifacts/m4-benchmark/new-local-retry
```

Only invalid cases are selected, with the same parameters. The merged summary
retains the original exclusions and replacement mapping. A second invalid run
returns nonzero; it does not keep trying until a preferable number appears.
Keep both the original and replacement directories.

## Generate the report

Using a separate Python environment containing matplotlib 3.11.2:

```sh
python -m scripts.m4_benchmark.report artifacts/m4-benchmark/new-local --output /tmp/infergate-new-local-report
```

Point the report at `new-local-retry` if you created a replacement run. The
[redraw guide](redraw-benchmarks.md) shows how to create the plotting environment.
Check input hashes, excluded cases, success rates, successful latency, and
three-round ranges before interpreting the plots. See the
[benchmark specification](../reference/benchmarks.md) for all profiles and
validity rules.
