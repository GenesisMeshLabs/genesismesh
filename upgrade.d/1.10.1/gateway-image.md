- **Gateway image: 1.10.1 follows 1.9.0.** No gateway image was published
  for 1.9.2 or 1.10.0. A deployment on `genesis-mesh-gateway:1.9.0` moves to
  `1.10.1` directly; its policy and durable state are read as before. The
  Network Authority and the SDKs change nothing in 1.10.1: upgrade them from
  1.10.0 when convenient.
