# Benchmark workflow

Run from `dryft/`. The ignored `.env` holds the team token; it is loaded automatically, so no token flags or shell setup are needed. Python and dependencies always come from the pinned uv environment.

On Windows, the short form is **`.\scripts\bench.ps1`**. Add `check`, `run`, `status`, or `rerun` as needed, e.g. **`.\scripts\bench.ps1 run`**. It selects the correct working directory and invokes pinned uv automatically. The portable commands below work on Linux too.

| Command | Action |
| --- | --- |
| `uv run --locked scripts/benchmark.py` | Wait for the tracked run and save results; safe to repeat. |
| `uv run --locked scripts/benchmark.py check` | Official archive validation and local helper tests, without GPU use. |
| `uv run --locked scripts/benchmark.py run` | Validate a clean, committed `main`, push it, find that exact commit's submission, and follow its auto-run. |
| `uv run --locked scripts/benchmark.py status` | Download current state and logs once. |
| `uv run --locked scripts/benchmark.py rerun` | Explicitly repeat the tracked remote submission; local edits are not uploaded. |

For an engine change: edit, run `check`, commit in the parent repository, then run `run`. The command never silently commits files, force-pushes, or rewrites history. Resolve remote divergence normally before retrying. Auto-run must remain enabled on the connected repository, with engine folder `dryft/engine`.

An existing run is reused. Explicit reruns persist an idempotency key before requesting a GPU, so an uncertain network response can be retried with the same key. Ctrl+C only stops waiting; the GPU run continues. The one-hour local wait limit also leaves it running. Do not run multiple benchmark commands concurrently.

Each run is saved in `results/<run-id>/`: complete run JSON, benchmark definition, metadata, console logs, and a readable summary. The state file remembers the current run. `results/` is ignored; copy only a reviewed, concise result summary into versioned docs. The raw output remains available for diagnosing correctness and latency failures.

The official score is output tokens per second, not percent of native. Public sample metrics help diagnose behavior; hidden workloads determine the ranking. Compare only matching benchmark specification digests, and retain all failures rather than selecting only favorable scores. Evaluate correctness, TTFT, TPOT, memory, and timing stability alongside throughput. Local validation does not establish GPU correctness or speed.

## Initial baseline

Completed: correct on all three reported public workloads, but failed batch-1 TTFT. See [measured baseline results](baseline.md).

- Engine: official starter, unchanged (`c2405f19fae577539969c5face3914b116757ae6`).
- Project commit: `bce9ba1836b2a7f2ccfd27694b0684c9c41c076f`.
- Submission: `66cd6085-4e78-4656-a2fa-a119c5c56b0f`.
- Run: `082bfed1-01ee-4354-97b3-53e34f5d535b`.
- [Live baseline](https://htn.dryft.ai/bench/deployments/03d3f101-d190-4001-99fd-dccabe6b116a).

The local packaging digest differs from the GitHub archive digest because their packaging differs; compare code/commit provenance, not archive hashes across different packagers.
