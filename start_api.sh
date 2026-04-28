#!/usr/bin/env bash
# Start the BackOfficePro REST API for the Android stocktake app.
# Run this from the BackOfficePro directory.
cd "$(dirname "$0")"
source venv/bin/activate 2>/dev/null || true
exec python api_server.py "$@"
