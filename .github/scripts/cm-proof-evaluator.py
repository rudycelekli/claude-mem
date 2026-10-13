#!/usr/bin/env python3
"""Validate actual Bun execution receipts; no inference from producer exit alone."""
import json
import re
import sys
from pathlib import Path


def counts(text):
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    result = {}
    for label in ('pass', 'fail', 'skip'):
        values = re.findall(r'^\s*(\d+) ' + label + r'$', text, re.M)
        if label == 'skip' and not values:
            result[label] = 0
        else:
            if len(values) != 1:
                raise ValueError('Missing or repeated ' + label + ' count')
            result[label] = int(values[0])
    executed = re.findall(r'^Ran (\d+) tests? across (\d+) files?\.', text, re.M)
    if len(executed) != 1:
        raise ValueError('Missing or repeated execution total')
    result['executed'], result['files'] = map(int, executed[0])
    if result['executed'] == 0 or result['files'] == 0:
        raise ValueError('No tests executed')
    if result['executed'] != sum(result[label] for label in ('pass', 'fail', 'skip')):
        raise ValueError('Execution total disagrees with outcome counts')
    return result


def terminal_counts(text):
    """The canonical full suite prints child Bun receipts before its own trailer."""
    clean = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    trailer = re.search(
        r'(?m)(?:^[ \t]*\d+ (?:pass|fail|skip)\n)+'
        r'(?:^[ \t]*\d+ expect\(\) calls\n)?'
        r'^Ran \d+ tests? across \d+ files?\.[^\n]*(?:\n|$)[ \t\r\n]*\Z',
        clean,
    )
    if trailer is None:
        raise ValueError('Missing terminal execution summary')
    return counts(trailer.group(0))


def record(text, producer_exit, writer_exit):
    if producer_exit != 0:
        raise ValueError('Canonical producer did not succeed')
    if writer_exit != 0:
        raise ValueError('Receipt writer did not succeed')
    result = terminal_counts(text)
    if result['pass'] <= 0 or result['fail'] != 0:
        raise ValueError('Full suite did not pass actual tests')
    return result


def validate(text, expected, producer_exit, expected_exit):
    if producer_exit != expected_exit:
        raise ValueError('Producer exit disagrees with the required outcome')
    actual = counts(text)
    for label in ('pass', 'fail', 'skip'):
        if actual[label] != expected[label]:
            raise ValueError('Unexpected ' + label + ' count')
    return actual


def self_test():
    positive = ' 2 pass\n 0 fail\nRan 2 tests across 1 file. [1s]\n'
    expected = {'pass': 2, 'fail': 0, 'skip': 0}
    validate(positive, expected, 0, 0)
    validate(' 0 pass\n 1 fail\nRan 1 test across 1 file. [1s]\n', {'pass': 0, 'fail': 1, 'skip': 0}, 1, 1)
    validate(' 51 pass\n 2 skip\n 0 fail\nRan 53 tests across 3 files. [3s]\n', {'pass': 51, 'fail': 0, 'skip': 2}, 0, 0)
    nested = (' 25 pass\n 0 fail\nRan 25 tests across 1 file. [1s]\n(child completed)\n'
              ' 16 pass\n 0 fail\nRan 16 tests across 1 file. [1s]\n(child completed)\n'
              ' 8686 pass\n 56 skip\n 0 fail\n 40168 expect() calls\n'
              'Ran 8742 tests across 867 files. [693.97s]\n')
    assert record(nested, 0, 0) == {'pass': 8686, 'fail': 0, 'skip': 56, 'executed': 8742, 'files': 867}
    terminal_bad = [
        ('earlier-green-final-fail', positive + ' 1 pass\n 1 fail\nRan 2 tests across 1 file. [1s]\n', 0),
        ('missing-terminal', positive + ' 2 pass\n', 0),
        ('zero-terminal', ' 0 pass\n 0 fail\nRan 0 tests across 1 file. [1s]\n', 0),
        ('all-skipped', ' 0 pass\n 2 skip\n 0 fail\nRan 2 tests across 1 file. [1s]\n', 0),
        ('inconsistent-terminal', positive.replace('Ran 2', 'Ran 3'), 0),
        ('producer-error-terminal-green', positive, 1),
        ('missing-terminal-fail-count', positive.replace(' 0 fail\n', ''), 0),
        ('duplicate-terminal-fail-count', positive.replace(' 0 fail\n', ' 0 fail\n 0 fail\n'), 0),
        ('trailing-contradiction', positive + 'trailing contradiction\n', 0),
    ]
    for name, invalid, producer in terminal_bad:
        try:
            record(invalid, producer, 0)
        except ValueError:
            continue
        raise AssertionError('Terminal evaluator accepted ' + name)
    try:
        record(positive, 0, 1)
    except ValueError:
        pass
    else:
        raise AssertionError('Evaluator accepted producer-success-tee-failure')
    bad = [
        ('missing-count', 'Ran 2 tests across 1 file. [1s]\n', 0, expected),
        ('zero-count', ' 0 pass\n 0 fail\nRan 0 tests across 1 file. [1s]\n', 0, {'pass': 0, 'fail': 0, 'skip': 0}),
        ('unexpected-count', positive, 0, {'pass': 1, 'fail': 0, 'skip': 0}),
        ('producer-error', positive, 1, expected),
        ('unexpected-skip', ' 2 pass\n 1 skip\n 0 fail\nRan 3 tests across 1 file. [1s]\n', 0, expected),
        ('wrong-total', ' 2 pass\n 0 fail\nRan 3 tests across 1 file. [1s]\n', 0, expected),
        ('duplicate-count', positive + ' 2 pass\n', 0, expected),
    ]
    for name, text, producer, wanted in bad:
        try:
            validate(text, wanted, producer, 0)
        except ValueError:
            continue
        raise AssertionError('Evaluator accepted ' + name)
    print(json.dumps({'self_test': 'PASS', 'accepted_controls': 4, 'terminal_rejected_controls': [case[0] for case in terminal_bad] + ['producer-success-tee-failure'], 'rejected_controls': [case[0] for case in bad]}))


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        self_test()
    elif sys.argv[1:2] == ['--record']:
        result = record(Path(sys.argv[2]).read_text(), int(sys.argv[3]), int(sys.argv[4]))
        print(json.dumps(result, sort_keys=True))
    else:
        log, passed, failed, skipped, producer, required = sys.argv[1:]
        result = validate(Path(log).read_text(), {'pass': int(passed), 'fail': int(failed), 'skip': int(skipped)}, int(producer), int(required))
        print(json.dumps(result, sort_keys=True))
