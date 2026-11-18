#!/bin/bash
# Start Bupa CareFlow V2 (creates + seeds backend/database/careflow_v2.db on FIRST start only; never resets it afterwards)
cd "$(dirname "$0")" && exec python3 -m backend.server
