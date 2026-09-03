# Project Standards

summarizer-api wraps two model providers behind one HTTP endpoint. The
deployment pins a model id per environment, so a retired id fails at
request time rather than at build time.

## Model ids

Pin a current model id in `deploy/*.yaml` and nowhere else. When a
provider announces a retirement, run the `model-upgrade` skill — it
carries the replacement table and rewrites the pinned ids.

## Testing

- Run `make test` before every push.
- Record provider responses with `make cassettes` when an id changes;
  the recorded fixtures name the model and go stale with it.
