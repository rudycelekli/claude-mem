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
    print(json.dumps({'self_test': 'PASS', 'accepted_controls': 3, 'rejected_controls': [case[0] for case in bad]}))


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        self_test()
    elif sys.argv[1:2] == ['--record']:
        result = counts(Path(sys.argv[2]).read_text())
        if result['pass'] <= 0 or result['fail'] != 0:
            raise ValueError('Full suite did not pass actual tests')
        print(json.dumps(result, sort_keys=True))
    else:
        log, passed, failed, skipped, producer, required = sys.argv[1:]
        result = validate(Path(log).read_text(), {'pass': int(passed), 'fail': int(failed), 'skip': int(skipped)}, int(producer), int(required))
        print(json.dumps(result, sort_keys=True))
