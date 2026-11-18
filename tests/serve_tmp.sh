#!/bin/bash
# start a throw-away V2 server on a temp database (for UI tests / screenshots)
export CAREFLOW_V2_DB=${1:-/tmp/ui_v2/database/careflow_v2.db} CAREFLOW_V2_UPLOADS=${2:-/tmp/ui_v2/uploads} CAREFLOW_V2_PORT=${3:-8798}
cd "$(dirname "$0")/.." && exec python3 -m backend.server --quiet
