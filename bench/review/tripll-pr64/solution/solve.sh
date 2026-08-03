#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "${SCRIPT_DIR}/golden_findings.json" "${AGENT_FINDINGS_PATH:-/workspace/findings.json}"
