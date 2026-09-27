# ml — Python training pipeline

- `datasets/`: telemetry traces recorded from the emulated system under
  randomized fault schedules. Generated data goes in `datasets/generated/`
  (gitignored).
- `training/`: feature extraction, episode-based train/validation/test splits,
  seeded training, and evaluation against the EWMA baseline
- `inference/`: the predictor interface loaded by `control-plane`
- `models/`: exported artifacts with a model card (seed, dataset hash, feature
  schema, metrics)

Implemented in Milestone 9. The model is advisory and runs periodically, never
per query.
