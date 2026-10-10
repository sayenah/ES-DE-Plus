#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Record actual dependency compiler/archive calls.
import json
import hashlib
import os
import sys

destination = os.environ.get('ESDE_LICENSE_COMMANDS')
arguments = sys.argv[1:]
if destination:
    record = {'directory': os.getcwd(), 'arguments': arguments}
    # Some library Makefiles do not retain header dependencies. Request a
    # compiler-produced depfile without replacing an existing build depfile.
    if '-c' in arguments and not {'-MD', '-MMD', '-M', '-MM'} & set(arguments) and any(
            arg.endswith(('.c', '.cpp', '.cc', '.cxx', '.S')) for arg in arguments):
        directory = os.path.join(os.path.dirname(destination), 'header-audit')
        os.makedirs(directory, exist_ok=True)
        identity = hashlib.sha256(json.dumps(record).encode()).hexdigest()
        dependency = os.path.join(directory, identity + '.d')
        arguments += ['-MD', '-MF', dependency]
        record['dependency'] = dependency
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        data = (json.dumps(record) + '\n').encode()
        assert os.write(descriptor, data) == len(data), 'Incomplete compiler audit record'
    finally:
        os.close(descriptor)
os.execv(arguments[0], arguments)
