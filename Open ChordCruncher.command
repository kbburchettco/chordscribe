#!/bin/bash
# Double-click this file to start ChordCruncher. Close the Terminal window to stop it.
cd "$(dirname "$0")" || exit 1

if [ ! -x .venv/bin/python ]; then
  echo "First run: installing ChordCruncher. This takes a few minutes..."
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || exit 1
fi

(
  until curl -s -o /dev/null http://127.0.0.1:8765/; do sleep 1; done
  open http://127.0.0.1:8765/
) &
exec .venv/bin/python server.py
