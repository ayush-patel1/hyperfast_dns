# control-plane — Python adaptive engine and management API

`hfdns-control` does three things:
- polls `hfdns-lb` telemetry every 500 ms;
- computes per-region backend scores (heuristic EWMA estimator or ML predictor)
  and pushes them as advice with a TTL;
- serves the management API used by the dashboard.

It is never on the per-query path. If it stops, the data plane's advice expires
and it falls back to built-in routing.

Implemented from Milestone 8 onward (management API endpoints from Milestone 6).
