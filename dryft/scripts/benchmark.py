"""Small, resumable official benchmark runner. Invoke through uv."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.client import Dryft, TERMINAL
from agent.package import package

STATE = ROOT / 'results' / 'benchmark-state.json'
BASELINE = {
    'submission_id': '66cd6085-4e78-4656-a2fa-a119c5c56b0f',
    'run_id': '082bfed1-01ee-4354-97b3-53e34f5d535b',
    'commit': 'bce9ba1836b2a7f2ccfd27694b0684c9c41c076f',
    'label': 'unchanged-starter',
}


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def validate() -> str:
    cli = ROOT / 'bin' / ('dryft.exe' if os.name == 'nt' else 'dryft')
    if not cli.is_file():
        raise RuntimeError('Install the official CLI first: ./install-dryft.ps1 or ./install-dryft.sh')
    subprocess.run([str(cli), 'validate', str(ROOT / 'engine')], check=True)
    archive = package(ROOT / 'engine')
    digest = hashlib.sha256(archive).hexdigest()
    print(f'Local engine SHA-256: {digest}', flush=True)
    return digest


def client() -> Dryft:
    # Read only our simple, ignored local token assignment. Environment wins.
    env_file = ROOT / '.env'
    if not os.environ.get('DRYFT_TOKEN') and env_file.exists():
        for line in env_file.read_text(encoding='utf-8-sig').splitlines():
            if line.startswith('DRYFT_TOKEN='):
                os.environ['DRYFT_TOKEN'] = line.split('=', 1)[1].strip().strip('\"\'')
    return Dryft('https://htn.dryft.ai')


def summary(run: dict) -> str:
    result = run.get('result') or {}
    lines = [f"Run {run.get('id')}: {run.get('state')}"]
    if result.get('score') is not None:
        lines.append(f"Official score: {result['score']} tok/s")
    for shape in result.get('shapes') or []:
        metrics = shape.get('modelMetrics') or {}
        lines.append(f"{shape.get('id')}: {shape.get('caseStatus')} | "
                     f"TPS={shape.get('tokensPerSecond')} | "
                     f"TTFT={metrics.get('ttftMs')} ms | TPOT={metrics.get('tpotMs')} ms")
        for value, reference, name in [
            ('ttftMs', 'referenceTtftMs', 'TTFT'),
            ('tpotMs', 'referenceTpotMs', 'TPOT'),
        ]:
            if metrics.get(value) is not None and metrics.get(reference):
                ratio = metrics[value] / metrics[reference]
                lines.append(f'  {name}: {ratio:.3f}x native' + (' — OVER 1.10x GATE' if ratio > 1.10 else ''))
        if shape.get('caseMessage'):
            lines.append(f"  {shape['caseMessage']}")
    for field in ('rankingReason', 'failureCode', 'failureMessage'):
        if result.get(field):
            lines.append(f'{field}: {result[field]}')
    for field in ('errorCode', 'errorMessage'):
        if run.get(field):
            lines.append(f'{field}: {run[field]}')
    return '\n'.join(lines)


def git(*args: str) -> str:
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def items(api: Dryft, endpoint: str) -> list[dict]:
    found = []
    cursor = None
    while True:
        path = endpoint + ('?cursor=' + quote(cursor, safe='') if cursor else '')
        page = api._send('GET', path)
        found.extend(page.get('items') or [])
        cursor = page.get('nextCursor')
        if not cursor:
            return found


def select_run(api: Dryft) -> dict:
    """Push a committed engine, discover its submission, reuse auto-run."""
    digest = validate()
    if git('status', '--porcelain'):
        raise RuntimeError('Commit your changes first. Benchmarking never silently commits files.')
    if git('branch', '--show-current') != 'main':
        raise RuntimeError('Switch to main: the connected repository submits its default branch.')
    commit = git('rev-parse', 'HEAD')
    pending = json.loads(STATE.read_text()) if STATE.exists() else {}
    # Recover the same intended run after an uncertain POST, without changing keys.
    if pending.get('pending_key'):
        raise RuntimeError('A rerun request is pending. Use rerun to recover its saved idempotency key.')
    submissions = items(api, '/api/v1/submissions')
    matching = next((s for s in submissions if s.get('commitSha') == commit), None)
    if not matching:
        # A failed push is safe to retry; never create an empty commit here.
        subprocess.run(['git', 'push', 'origin', 'HEAD:main'], cwd=ROOT, check=True)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            matching = next((s for s in items(api, '/api/v1/submissions')
                             if s.get('commitSha') == commit), None)
            if matching:
                break
            time.sleep(5)
        if not matching:
            raise RuntimeError('No submission for HEAD yet. Check GitHub delivery in Repositories; retry safely.')
    state = {'submission_id': matching['id'], 'commit': commit, 'local_archive_sha256': digest}
    # Give the push webhook a chance to attach its official auto-run.
    for _ in range(12):
        runs = [r for r in items(api, '/api/v1/runs') if r.get('submissionId') == matching['id']]
        if runs:
            state['run_id'] = max(runs, key=lambda r: r.get('createdAt', ''))['id']
            save(STATE, state)
            return state
        time.sleep(5)
    raise RuntimeError('Submission exists but no auto-run yet. Check auto-run settings; no duplicate was started.')


def collect(api: Dryft, state: dict, wait: bool) -> bool:
    folder = ROOT / 'results' / state['run_id']
    deadline = time.monotonic() + 3600
    previous = None
    while True:
        run = api.run(state['run_id'])
        save(folder / 'run.json', run)
        save(folder / 'metadata.json', state)
        if run.get('state') != previous:
            print(summary(run), flush=True)
            previous = run.get('state')
        if run.get('state') in TERMINAL or not wait:
            break
        if time.monotonic() >= deadline:
            print('Still running. Re-run the same command to resume; no duplicate is created.')
            return False
        time.sleep(15)
    (folder / 'summary.txt').write_text(summary(run) + '\n', encoding='utf-8')
    after = -1
    pages = []
    while True:
        page = api.logs(state['run_id'], after=after)
        pages.append(page)
        next_after = page.get('nextAfter', after)
        if page.get('complete') or not page.get('items') or next_after <= after:
            break
        after = next_after
    save(folder / 'logs.json', {'pages': pages})
    print(f'Results saved in {folder}', flush=True)
    return run.get('state') == 'succeeded'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='watch', choices=['check', 'run', 'watch', 'status', 'rerun'])
    args = parser.parse_args()
    if args.action == 'check':
        validate()
        subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=ROOT, check=True)
        return 0
    api = client()
    state = json.loads(STATE.read_text()) if STATE.exists() else dict(BASELINE)
    if args.action == 'run':
        state = select_run(api)
    if args.action == 'rerun':
        # Re-evaluate the tracked remote submission, never imply local edits are uploaded.
        if not state.get('pending_key') and state.get('run_id') and api.run(state['run_id']).get('state') not in TERMINAL:
            print('An existing run is active; resuming it instead of creating a duplicate.')
        else:
            if not state.get('pending_key'):
                state['pending_key'] = str(uuid.uuid4())
                save(STATE, state)  # Save before POST so an uncertain retry reuses this key.
            run = api.start_run(state['submission_id'], mode='official', idempotency_key=state['pending_key'])
            state['run_id'] = run['id']
            state.pop('pending_key', None)
            save(STATE, state)
    else:
        save(STATE, state)
    save(ROOT / 'results' / state['run_id'] / 'benchmark.json', api.benchmark())
    succeeded = collect(api, state, wait=args.action != 'status')
    return 0 if succeeded else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nStopped waiting. The remote run continues; rerun to resume.', file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f'Benchmark error: {error}', file=sys.stderr)
        raise SystemExit(1)
