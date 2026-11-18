#!/bin/bash
# V1 workflows (data import → appointment → consultation → test → result → care gap → AI → outcome) re-run against V2 + SQLite
cd "$(dirname "$0")/.." ; T=$(mktemp -d); export CAREFLOW_V2_DB=$T/database/careflow_v2.db CAREFLOW_V2_UPLOADS=$T/uploads CAREFLOW_V2_PORT=8797
python3 -m backend.server --quiet >$T/server.log 2>&1 & SP=$!
for i in $(seq 1 40); do curl -s localhost:8797/api/health >/dev/null && break; sleep 0.25; done
URL=http://127.0.0.1:8797/ node tests/e2e_v1_flows.js 2>&1 | grep -v -e agent-proxy -e connect_rejected
echo "--- database check (read directly from SQLite after the UI run)"
python3 - <<PY
import sqlite3
c=sqlite3.connect("$T/database/careflow_v2.db"); c.execute("PRAGMA foreign_keys=ON")
q=lambda s:c.execute(s).fetchone()[0]
print("patients:",q("select count(*) from patients"),"| Zara:",q("select count(*) from patients where first_name='Zara'"),
 "| her appts:",q("select count(*) from appointments where patient_id=(select id from patients where first_name='Zara')"),
 "| her consultations:",q("select count(*) from consultations where patient_id=(select id from patients where first_name='Zara')"),
 "| her tests:",q("select count(*) from diagnostic_tests where patient_id=(select id from patients where first_name='Zara')"),
 "| prio history rows for Zara:",q("select count(*) from priority_history where patient_id=(select id from patients where first_name='Zara')"),
 "| FK violations:",len(c.execute("pragma foreign_key_check").fetchall()))
PY
kill -INT $SP 2>/dev/null; wait $SP 2>/dev/null; echo "server log:"; tail -3 $T/server.log; rm -rf $T
