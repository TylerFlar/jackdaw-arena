#!/bin/sh
# Run the engine tests inside the built image: the Linux x86_64 build of jackdaw that Lambda
# runs must replay and match BalatroGymnasiumEnv byte for byte, like the developer's build.
#   docker run --rm --user root -v "$PWD/api:/api:ro" arena-api sh /api/scripts/test-in-image.sh
set -eu
/usr/local/bin/python -m pip install --quiet --disable-pip-version-check --target /tmp/pytest pytest
cp -r /api/tests /tmp/tests
cd /tmp
PYTHONPATH=/tmp/pytest /app/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_live.py
