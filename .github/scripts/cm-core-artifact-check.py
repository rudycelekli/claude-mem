#!/usr/bin/env python3
"""Verify immutable core receipts before executing stages the evaluator blocked."""
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location('evaluator', Path(__file__).with_name('cm-proof-evaluator.py'))
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)

CORE_STEPS = [
    'Source identity and runtime receipt',
    'Install dependencies (canonical CI command)',
    'Verify committed plugin bundles before rebuilding',
    'Exact-base negative control',
    'Typecheck root and viewer (canonical CI command)',
    'Build with bundle-size guards (canonical CI command)',
    'Preserve generated artifact diff and authored source hashes',
    'Positive regression with exact executed count',
]


def verify(row, run, artifact, job, job_log, files):
    if run['id'] != row['run_id'] or run['head_sha'] != row['proof_head']:
        raise ValueError('Wrong original run identity')
    if artifact['id'] != row['artifact_id'] or artifact['expired'] or artifact['digest'] != row['artifact_digest']:
        raise ValueError('Wrong immutable artifact identity')
    if artifact['workflow_run']['id'] != row['run_id'] or artifact['workflow_run']['head_sha'] != row['proof_head']:
        raise ValueError('Artifact came from a different source run')
    if job['id'] != row['job_id'] or job['run_id'] != row['run_id'] or job['status'] != 'completed' or job['conclusion'] != 'failure':
        raise ValueError('Original job is not the recorded completed evaluator failure')
    steps = {step['name']: step['conclusion'] for step in job['steps']}
    if any(steps.get(name) != 'success' for name in CORE_STEPS):
        raise ValueError('A required original core stage did not pass')
    if steps.get('Full repository Bun suite (canonical CI command)') != 'failure':
        raise ValueError('Unexpected original full-suite stage outcome')
    # The pinned original shell used set -euo pipefail and reached Python
    # after Bun | tee. Therefore BOTH producer and writer exited zero. Keep
    # this structural exit evidence explicit; the old job is still failed.
    for marker in [
        'set -euo pipefail',
        'bun test tests 2>&1 | tee "$RUNNER_TEMP/cmem-proof/full-suite.log"',
        'ValueError: Missing or repeated pass count',
        'cm-proof-evaluator.py --record',
    ]:
        if marker not in job_log:
            raise ValueError('Missing original pipeline/evaluator evidence')
    for name, wanted in row['file_hashes'].items():
        if hashlib.sha256(files[name]).hexdigest() != wanted:
            raise ValueError('Changed artifact file: ' + name)
    if files['head.txt'].decode().strip() != row['head']:
        raise ValueError('Wrong candidate source in artifact')
    if files['node.txt'].decode().strip() != row['node'] or files['bun.txt'].decode().strip() != row['bun']:
        raise ValueError('Wrong original runtime')
    full = evaluator.record(files['full-suite.log'].decode(), 0, 0)
    if full != row['full_counts']:
        raise ValueError('Changed full-suite outcome')
    evaluator.validate(files['before.log'].decode(), row['before_counts'], 1, 1)
    evaluator.validate(files['after.log'].decode(), row['after_counts'], 0, 0)
    return {'source': row['head'], 'original_job_conclusion': 'failure', 'reused_full_counts': full,
            'producer_exit': 0, 'writer_exit': 0, 'exit_evidence': 'Pinned set -euo pipefail reached evaluator after Bun | tee'}


def api_command(path, raw=False):
    # Raw log bytes go to a captured buffer/file, never terminal rendering.
    return ['gh', 'api', 'repos/rudycelekli/claude-mem/' + path] + (['--allow-escape-sequences'] if raw else [])


def api(path, raw=False):
    result = subprocess.check_output(api_command(path, raw))
    return result.decode() if raw else json.loads(result)


def self_test():
    assert api_command('actions/jobs/3/logs', True)[-1] == '--allow-escape-sequences'
    assert '--allow-escape-sequences' not in api_command('actions/jobs/3', False)
    files = {'head.txt': b'candidate\n', 'node.txt': b'v20.20.2\n', 'bun.txt': b'1.4.3\n',
             'before.log': b' 0 pass\n 1 fail\nRan 1 test across 1 file. [1s]\n',
             'after.log': b' 1 pass\n 0 fail\nRan 1 test across 1 file. [1s]\n',
             'full-suite.log': b' 2 pass\n 1 skip\n 0 fail\nRan 3 tests across 2 files. [1s]\n'}
    row = {'run_id': 1, 'proof_head': 'proof', 'artifact_id': 2, 'artifact_digest': 'sha256:artifact',
           'job_id': 3, 'head': 'candidate', 'node': 'v20.20.2', 'bun': '1.4.3',
           'file_hashes': {name: hashlib.sha256(value).hexdigest() for name, value in files.items()},
           'full_counts': {'pass': 2, 'skip': 1, 'fail': 0, 'executed': 3, 'files': 2},
           'before_counts': {'pass': 0, 'skip': 0, 'fail': 1}, 'after_counts': {'pass': 1, 'skip': 0, 'fail': 0}}
    run = {'id': 1, 'head_sha': 'proof'}
    artifact = {'id': 2, 'expired': False, 'digest': 'sha256:artifact', 'workflow_run': run}
    job = {'id': 3, 'run_id': 1, 'status': 'completed', 'conclusion': 'failure',
           'steps': [{'name': name, 'conclusion': 'success'} for name in CORE_STEPS]
                    + [{'name': 'Full repository Bun suite (canonical CI command)', 'conclusion': 'failure'}]}
    log = 'set -euo pipefail\nbun test tests 2>&1 | tee "$RUNNER_TEMP/cmem-proof/full-suite.log"\ncm-proof-evaluator.py --record\nValueError: Missing or repeated pass count'
    verify(row, run, artifact, job, log, files)
    bad = []
    wrong = copy.deepcopy(run); wrong['head_sha'] = 'other'; bad.append(('wrong-proof-head', row, wrong, artifact, job, log, files))
    wrong = copy.deepcopy(artifact); wrong['digest'] = 'other'; bad.append(('wrong-artifact-digest', row, run, wrong, job, log, files))
    wrong = copy.deepcopy(artifact); wrong['expired'] = True; bad.append(('expired-artifact', row, run, wrong, job, log, files))
    wrong = copy.deepcopy(job); wrong['status'] = 'in_progress'; bad.append(('unfinished-job', row, run, artifact, wrong, log, files))
    wrong = copy.deepcopy(job); wrong['steps'][2]['conclusion'] = 'failure'; bad.append(('failed-core-stage', row, run, artifact, wrong, log, files))
    bad.append(('missing-pipeline-exit-evidence', row, run, artifact, job, '', files))
    wrong = copy.deepcopy(files); wrong['head.txt'] = b'other'; bad.append(('changed-artifact-content', row, run, artifact, job, log, wrong))
    wrong = copy.deepcopy(row); wrong['head'] = 'other'; bad.append(('wrong-candidate-source', wrong, run, artifact, job, log, files))
    wrong = copy.deepcopy(row); wrong['node'] = 'other'; bad.append(('wrong-runtime', wrong, run, artifact, job, log, files))
    wrong = copy.deepcopy(row); wrong['full_counts']['pass'] = 1; bad.append(('changed-full-suite-count', wrong, run, artifact, job, log, files))
    for name, *args in bad:
        try:
            verify(*args)
        except ValueError:
            continue
        raise AssertionError('Artifact guard accepted ' + name)
    print(json.dumps({'self_test': 'PASS', 'accepted_synthetic_controls': 1, 'rejected_controls': [case[0] for case in bad]}))


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        self_test()
        sys.exit(0)
    manifest_path, candidate, artifact_path, output_path = sys.argv[1:]
    manifest = json.loads(Path(manifest_path).read_text())
    row = next(row for row in manifest if row['id'] == candidate)
    run = api('actions/runs/' + str(row['run_id']))
    artifact = api('actions/artifacts/' + str(row['artifact_id']))
    job = api('actions/jobs/' + str(row['job_id']))
    job_log = api('actions/jobs/' + str(row['job_id']) + '/logs', raw=True)
    files = {name: (Path(artifact_path) / name).read_bytes() for name in row['file_hashes']}
    result = verify(row, run, artifact, job, job_log, files)
    output = Path(output_path)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'original-run.json').write_text(json.dumps(run))
    (output / 'original-artifact.json').write_text(json.dumps(artifact))
    (output / 'original-job.json').write_text(json.dumps(job))
    (output / 'original-job.log').write_text(job_log)
    (output / 'reused-core-receipt.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
