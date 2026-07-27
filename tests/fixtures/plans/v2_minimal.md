# Demo Feature — v2 fixture

waveorch_format = 2
title = "Demo"
slug = "demo"
base = "main"

[[waves]]
id = "W1"
title = "Tests"
role = "test-author"
verify = ["make lint"]

[[waves]]
id = "W2"
title = "Implement"
role = "impl"

  [[waves.depends_on]]
  wave = "W1"
  reason = "contract"
