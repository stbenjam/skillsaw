---
name: refunds
description: Process customer refund requests per Acme's refund policy. Use when a customer asks for their money back or disputes a charge.
license: Apache-2.0
---

# Refunds

1. Look up the order with the `get_order` tool.
2. Check the request against the [refund policy](references/policy.md).
3. Issue the refund with `create_refund`, or explain to the customer why the
   request does not qualify.
