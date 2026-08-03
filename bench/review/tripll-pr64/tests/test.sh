#!/bin/bash
set -euo pipefail
ACTUAL="${AGENT_FINDINGS_PATH:-/workspace/findings.json}"
python3 /tests/verify_findings.py "$ACTUAL" /tests/expected_findings.json
if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
