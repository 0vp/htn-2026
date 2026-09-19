# Unchanged starter baseline — September 19, 2026

The official run completed in about 5 minutes 38 seconds. All three reported public workloads produced correct output. The run failed the batch-1 time-to-first-token gate, so there is **no official score or leaderboard rank**.

| Public workload | Output tok/s | TTFT ms | Native TTFT ms | TPOT ms | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| B1, 512 input → 32 output | 35.86 | 33.04 | 28.74 | 27.70 | TTFT failed |
| B4, 2048 input → 32 output | 118.09 | 202.66 | 202.37 | 28.42 | Passed |
| B16, 512 input → 128 output | 547.05 | 192.04 | 191.99 | 27.97 | Passed |

Batch-1 TTFT was approximately **1.149× native**, above the allowed **1.10×** (about 31.62 ms). Its TPOT was approximately 1.003× native and did not explain the failure. Five measured samples were reported for each public workload. These are observations from one official run, not a stable estimate across repeated runs. A future repeated baseline can help distinguish persistent overhead from measurement variation; do not assume the cause from this run alone.

The result exposed only public workloads. Hidden-workload performance cannot be inferred from this table. The platform returned `latency_limit` and a generic ranking-verification message; the explicit case failure identifies the observed gate failure.

## Provenance

- [Live run page](https://htn.dryft.ai/bench/deployments/03d3f101-d190-4001-99fd-dccabe6b116a)
- Run: `082bfed1-01ee-4354-97b3-53e34f5d535b`
- Submission: `66cd6085-4e78-4656-a2fa-a119c5c56b0f`
- Project commit: `bce9ba1836b2a7f2ccfd27694b0684c9c41c076f`
- Starter revision: `c2405f19fae577539969c5face3914b116757ae6`, engine unchanged
- Benchmark specification: `ff85e115fb9f4b4ef389b8307cd867ad5af5db628785874d44bc9e8378e7eaa7`
- Hardware reported: NVIDIA H100 80GB HBM3; driver 580.95.05
- Runtime: `triton-cu124-py311`, harness 0.2.0, report version 2
- Platform interpreter reported: Python 3.11.5. Local preparation remains explicitly pinned to 3.11.14.
- Local raw report: `results/082bfed1-01ee-4354-97b3-53e34f5d535b/run.json`, alongside benchmark definition, metadata, logs, and summary.

See [benchmarking](benchmarking.md) for one-command checks and reruns. Preserve this failed baseline when comparing future experiments.
