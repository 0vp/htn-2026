"""Summarize official scores alongside paired native latency measurements."""
import json
from pathlib import Path


def comparison(run: dict) -> list[dict]:
    rows = []
    for shape in (run.get('result') or {}).get('shapes', []):
        metrics = shape.get('modelMetrics') or {}
        row = {'shape': shape['id'], 'status': shape.get('caseStatus'),
               'tps': shape.get('tokensPerSecond')}
        for name, reference in [('ttftMs', 'referenceTtftMs'), ('tpotMs', 'referenceTpotMs')]:
            value, native = metrics.get(name), metrics.get(reference)
            row[name + 'Ratio'] = value / native if value is not None and native else None
        rows.append(row)
    return rows


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    state = json.loads((root / 'results/sweep.json').read_text())
    print('Official scores include hidden workloads; ratios below describe public workloads only.')
    print('Ratios below 1 mean lower latency than the native model in that same run.')
    for name, entry in state['experiments'].items():
        print(f"\n{name}: {entry.get('state', 'pending')} score={(entry.get('result') or {}).get('score')}")
        if entry.get('spec_digest') and entry['spec_digest'] != state['spec_digest']:
            print('  Specification mismatch: do not compare.')
            continue
        for row in comparison(entry):
            print(' ', json.dumps(row))


if __name__ == '__main__':
    main()
