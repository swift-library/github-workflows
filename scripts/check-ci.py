#!/usr/bin/env python3
"""Require every CI dependency to succeed."""

import json
import os


def check(needs):
    for name, result in needs.items():
        if result['result'] != 'success':
            raise ValueError(f'{name}: expected success, got {result["result"]}')


if __name__ == '__main__':
    check(json.loads(os.environ['NEEDS']))
    print('All CI checks passed')
