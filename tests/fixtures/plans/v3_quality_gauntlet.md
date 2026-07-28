waveorch_format = 3
title = "Quality gauntlet fixture"
slug = "quality-gauntlet-fixture"
base = "main"
branch = "wave/quality-gauntlet-fixture"
target_repo = "sevn-bot/tripll"

[[waves]]
id = "W3"
title = "Deployment menu section"
role = "impl"
effort = "M"
decomposition = "gauntlet"
targets = ["src/tripll/gateway/menu/deployment.py"]
verify = ["make lint", "make test"]

  [waves.outcome]
  required = ["tests/gateway/test_menu_deployment.py passes"]
  forbidden = ["edit tests/ from impl wave"]
  evidence = ["test_output", "artifact_capture"]

    [waves.outcome.reference]
    kind = "html_crop"
    path = "docs/examples/menu-deployment.html#deployment"
    comparison = "blind_ab"
    stop_when = "reference_wins"

    [waves.outcome.quality_gauntlet]
    enabled = true
    max_rounds = 5
    sub_budget_usd = 2.0
    decomposition = "prescribed"
    smoothing = true
