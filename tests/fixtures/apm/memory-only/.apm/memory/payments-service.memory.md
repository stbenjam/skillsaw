# Payments service memory

- The ledger service owns every balance mutation; other services call its gRPC API.
- Refunds go through `refund-orchestrator`, which retries idempotently on the
  `refund_id` key.
- Integration tests run against the `payments-sandbox` namespace; never point
  them at staging.
