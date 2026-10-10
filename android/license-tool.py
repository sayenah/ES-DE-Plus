#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. Record actual dependency compiler/archive calls.
import json
import os
import sys

destination = os.environ.get('ESDE_LICENSE_COMMANDS')
if destination:
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        record = json.dumps({'directory': os.getcwd(), 'arguments': sys.argv[1:]}) + '\n'
        data = record.encode()
        assert os.write(descriptor, data) == len(data), 'Incomplete compiler audit record'
    finally:
        os.close(descriptor)
os.execv(sys.argv[1], sys.argv[1:])
