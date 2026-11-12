"""Run exact retained film helpers, including deliberate gate and caption probes."""
import json
import os
from pathlib import Path
import subprocess

base = Path(__file__).resolve().parent
runtime = base / 'runtime'
out = base / 'outputs'
out.mkdir(exist_ok=True)
url = (runtime / 'acceptance.html').as_uri()
cases = [
    ('representative-still', '?mode=scene', ['--still', '--gate']),
    ('representative-compact', '?mode=scene', ['--still', '--reduced', '--width', '390', '--gate']),
    ('representative-loop', '?mode=scene', ['--every', '1000', '--count', '8', '--gate']),
    ('failure', '?mode=failure', ['--states', '--states-for', '2200', '--every', '300', '--gate']),
]
results = []
for name, query, args in cases:
    env = dict(os.environ)
    if name == 'failure':
        env['NODE_OPTIONS'] = '--import=' + str(runtime / 'audit-hooks.mjs')
        env['CAPTION_AUDIT'] = str(out / 'caption-audit.json')
    command = ['node', 'scripts/film.mjs', url + query, '--out', str(out / (name + '.png')),
               '--report', str(out / (name + '.json')), *args]
    result = subprocess.run(command, cwd=runtime, env=env, text=True, capture_output=True, timeout=90)
    (out / (name + '.log')).write_text(result.stdout + result.stderr)
    results.append({'case': name, 'exitCode': result.returncode, 'expectedFailure': name == 'failure'})
    print(json.dumps(results[-1]), flush=True)
(out / 'film-results.json').write_text(json.dumps(results, indent=2) + '\n')
caption = json.loads((out / 'caption-audit.json').read_text())
assert caption['escaped'] and caption['injected'] == 0 and caption['executed'] == 0
assert any('<img' in text and "'single'" in text and '"double"' in text for text in caption['payloads'])
failure = results[-1]
assert failure['exitCode'] in (1, 2)
assert 'rehearsal failed:' in (out / 'failure.log').read_text()
assert 'rehearsal passed' not in (out / 'failure.log').read_text()
assert json.loads((out / 'failure.json').read_text())['exitCode'] == failure['exitCode']
assert all(case['exitCode'] == 0 for case in results[:-1]), results
