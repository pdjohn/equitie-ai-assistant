#!/usr/bin/env bash
# One-shot setup + run for the EquiTie Investor Assistant.
#   ./run.sh            -> launch the Streamlit web app
#   ./run.sh cli INV001 -> launch the CLI for a given investor
#   ./run.sh test       -> run the verification suite
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating virtualenv + installing deps..."
  python3 -m venv .venv
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt
fi
PY=./.venv/bin/python

case "${1:-app}" in
  test) exec $PY -m pytest tests/ -q ;;
  cli)  exec $PY cli.py --investor "${2:-INV001}" ;;
  app)  exec ./.venv/bin/streamlit run app.py ;;
  *)    echo "usage: ./run.sh [app|cli <INVID>|test]"; exit 1 ;;
esac
