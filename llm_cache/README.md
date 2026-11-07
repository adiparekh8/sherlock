# LLM cache

One JSON file per LLM call, keyed by a hash of model, task, prompt version, input text, and output schema.
`source` is `api` for real model output or `stub` for the deterministic no-key fallback. With a key present,
stub entries are recomputed and overwritten. Commit this directory so the demo is reproducible without a key.
