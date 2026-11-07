# LLM cache

One JSON file per LLM call, keyed by a hash of model, task, prompt version, input text, and output schema.
Only real API output is cached (`source: api`). Without a key and without a cached entry the deterministic
stub in sherlock/llm/stub.py answers instead, and its output is never cached. Commit this directory so a
keyed run's results are reproducible on machines without a key.
