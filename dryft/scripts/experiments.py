"""Sequential, restartable official experiment sweep. Never force-push."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.error import URLError

try:
    from .benchmark import ROOT, client, collect, git, items, save, validate, TERMINAL
except ImportError:
    from benchmark import ROOT, client, collect, git, items, save, validate, TERMINAL
from agent.client import ApiError

STATE = ROOT / 'results' / 'sweep.json'
CONTROL = '4eec26fe-79bb-4af7-ad78-b4b28355a154'
ORDER = ['norms', 'all_norms', 'speculative', 'suffix', 'suffix_batch',
         'graph', 'graph_hybrid', 'graph_fused', 'graph_folded', 'graph_residual',
         'graph_tuned', 'graph_verify', 'graph_rope', 'graph_norms',
         'direct', 'gqa', 'folded_gqa', 'static', 'swiglu', 'packed',
         'head_gemv', 'custom_attention', 'combined']


def choose_winner(state: dict) -> str:
    """Keep the control unless a comparable, ranked candidate beats it."""
    scores = {'baseline': state['control_result']['score']}
    for name, entry in state['experiments'].items():
        result = entry.get('result') or {}
        if (entry.get('state') == 'succeeded' and result.get('ranked')
                and entry.get('spec_digest') == state['spec_digest']
                and isinstance(result.get('score'), (int, float))):
            scores[name] = result['score']
    return max(scores, key=scores.get)


def select(name: str) -> None:
    path = ROOT / 'engine' / 'options.py'
    text = path.read_text(encoding='utf-8')
    text, count = re.subn(r"^ACTIVE = '[a-z_]+'$", f"ACTIVE = '{name}'", text, flags=re.M)
    if count != 1:
        raise RuntimeError('Cannot select experiment configuration')
    path.write_text(text, encoding='utf-8')


def wait_run(api, run_id: str) -> dict:
    last = None
    forbidden_retries = 0
    while True:
        try:
            run = api.run(run_id)
        except (ApiError, URLError, TimeoutError, ConnectionError) as error:
            if isinstance(error, ApiError):
                if error.status == 403 and error.code == 'http_error' and forbidden_retries < 2:
                    # Observed transient proxy response; retry only the same authorized GET.
                    forbidden_retries += 1
                elif error.status not in (408, 429, 500, 502, 503, 504):
                    raise
            print(f'{run_id}: status unavailable; retrying this same run in 20 seconds', flush=True)
            time.sleep(20)
            continue
        forbidden_retries = 0
        save(ROOT / 'results' / run_id / 'run.json', run)
        if run['state'] != last:
            print(f"{run_id}: {run['state']}", flush=True)
            last = run['state']
        if run['state'] in TERMINAL:
            return run
        time.sleep(20)


def ensure_pushed(commit: str) -> None:
    """Resume observing a delivered commit without pushing newer local work."""
    subprocess.run(['git', 'fetch', 'origin'], cwd=ROOT, check=True)
    ancestry = subprocess.run(
        ['git', 'merge-base', '--is-ancestor', commit, 'origin/main'], cwd=ROOT)
    if ancestry.returncode == 0:
        return
    if ancestry.returncode != 1:
        raise RuntimeError('Cannot verify experiment ancestry on origin/main.')
    if git('rev-parse', 'HEAD') != commit or git('status', '--porcelain'):
        raise RuntimeError('Checkout differs from unpushed experiment; reconcile before pushing.')
    subprocess.run(['git', 'push', 'origin', 'HEAD:main'], cwd=ROOT, check=True)


def discover(api, commit: str) -> dict:
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        runs = [r for r in items(api, '/api/v1/runs') if r.get('commitSha') == commit]
        if runs:
            return max(runs, key=lambda r: r['createdAt'])
        time.sleep(10)
    raise RuntimeError('Push has no run yet; check delivery, then resume sweep without creating a new commit.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()
    state = json.loads(STATE.read_text()) if STATE.exists() else {
        'control_run': CONTROL, 'experiments': {}, 'complete': False,
        'started': datetime.now(timezone.utc).isoformat(),
    }
    if args.status:
        print(json.dumps(state, indent=2))
        return
    api = client()
    control = wait_run(api, state['control_run'])
    if control['state'] != 'succeeded' or not (control.get('result') or {}).get('ranked'):
        raise RuntimeError('Control must pass and rank before comparative experiments.')
    state['spec_digest'] = control['challengeSpecDigest']
    state['control_result'] = control.get('result')
    save(STATE, state)
    collect(api, {'run_id': control['id'], 'label': 'control',
                  'submission_id': control['submissionId'], 'commit': control.get('commitSha')}, False)
    for name in ORDER:
        record = state['experiments'].setdefault(name, {})
        if record.get('finished'):
            continue
        if api.benchmark()['specDigest'] != state['spec_digest']:
            raise RuntimeError('Benchmark definition changed; establish a new control before continuing.')
        if not record.get('commit'):
            if git('status', '--porcelain'):
                raise RuntimeError('Working tree changed outside sweep; save work before resuming.')
            # Fetch and fast-forward only; never discard collaborators or rewrite their history.
            subprocess.run(['git', 'fetch', 'origin'], cwd=ROOT, check=True)
            subprocess.run(['git', 'merge', '--ff-only', 'origin/main'], cwd=ROOT, check=True)
            active = [r for r in items(api, '/api/v1/runs') if r['state'] not in TERMINAL]
            for run in active:
                wait_run(api, run['id'])
            select(name)
            record['local_archive_sha256'] = validate()
            subprocess.run(['git', 'add', 'engine/options.py'], cwd=ROOT, check=True)
            subprocess.run(['git', 'commit', '-m', f'Dryft experiment: {name}'], cwd=ROOT, check=True)
            record['commit'] = git('rev-parse', 'HEAD')
            save(STATE, state)
        if not record.get('run_id'):
            ensure_pushed(record['commit'])
            run = discover(api, record['commit'])
            record.update(run_id=run['id'], submission_id=run['submissionId'])
            save(STATE, state)
        result = wait_run(api, record['run_id'])
        record.update(finished=True, state=result['state'], result=result.get('result'),
                      error=result.get('errorMessage'), spec_digest=result['challengeSpecDigest'])
        save(STATE, state)
        collect(api, dict(record, label=name), False)
    winner = choose_winner(state)
    if git('status', '--porcelain'):
        raise RuntimeError('Working tree changed; reconcile before selecting winner.')
    select(winner)
    validate()
    subprocess.run(['git', 'add', 'engine/options.py'], cwd=ROOT, check=True)
    if git('diff', '--cached', '--name-only'):
        subprocess.run(['git', 'commit', '-m', f'Select measured Dryft configuration: {winner}'], cwd=ROOT, check=True)
        subprocess.run(['git', 'push', 'origin', 'HEAD:main'], cwd=ROOT, check=True)
        state['confirmation_commit'] = git('rev-parse', 'HEAD')
        save(STATE, state)
    if not state.get('confirmation_run'):
        if state.get('confirmation_commit'):
            confirmation = discover(api, state['confirmation_commit'])
        else:
            # The last candidate can already be the winner. Confirm it independently.
            import uuid
            if not state.get('confirmation_key'):
                state['confirmation_key'] = str(uuid.uuid4())
                save(STATE, state)
            entry = state['experiments'][winner]
            confirmation = api.start_run(entry['submission_id'], mode='official',
                                         idempotency_key=state['confirmation_key'])
        state['confirmation_run'] = confirmation['id']
        save(STATE, state)
    checked = wait_run(api, state['confirmation_run'])
    state['confirmation_result'] = checked
    save(STATE, state)
    collect(api, {'run_id': checked['id'], 'submission_id': checked['submissionId'],
                  'label': 'confirmation', 'commit': checked.get('commitSha')}, False)
    if (checked['state'] != 'succeeded' or not (checked.get('result') or {}).get('ranked')
            or checked['challengeSpecDigest'] != state['spec_digest']
            or (checked['result']['score'] <= state['control_result']['score'] and winner != 'baseline')):
        raise RuntimeError('Final confirmation did not pass or beat control; selection is not verified.')
    state.update(complete=True, selected=winner)
    save(STATE, state)
    print(f'Sweep complete; selected {winner}', flush=True)


if __name__ == '__main__':
    main()
