waveorch_format = 3
title = "Code factory L1"
slug = "code-factory-l1"
base = "main"
branch = "wave/code-factory-l1"
target_repo = "sevn-bot/tripll"

[pipeline]
max_turns = 3
deadline = "6h"
budget_usd = 25.0

[[waves]]
id = "W2"
title = "GraphStore"
role = "impl"
effort = "M"
targets = ["src/tripll/graphstore/sqlite_store.py"]
verify = ["make lint", "make test"]

  [[waves.depends_on]]
  wave = "W1"
  reason = "contract"
  detail = "RED suite from test-creator"

  [waves.outcome]
  required = ["tests/test_graphstore.py collects"]
  forbidden = ["edit tests/ from impl wave"]
  evidence = ["test_output", "final_diff"]
