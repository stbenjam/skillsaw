---
name: ledger-query
description: Query the ledger replica for transfers, balances, and audit rows. Use when debugging data issues in acme-api.
---

# Ledger Query

Use the query tool to pull rows from the ledger replica. For example:

    query(sql="SELECT * FROM transfers WHERE id = 42")

Another example, limiting columns:

    query(sql="SELECT amount FROM transfers WHERE id = 42")

A third example, joining audit rows:

    query(sql="SELECT * FROM audit WHERE transfer_id = 42")

Never run queries against the primary; the replica lags at most 30
seconds and that is always acceptable for debugging.
