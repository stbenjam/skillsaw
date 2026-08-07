# acme-api

acme-api is the Go ledger service behind the transfers dashboard. Use
these notes for every change in this repository.

## Using the search tool

When you need to find a symbol, use the search tool. For example:

```
search(query="TransferFunds", type="symbol")
```

Another example, searching for a file:

```
search(query="ledger.go", type="file")
```

A third example, searching text:

```
search(query="fixed-point", type="text")
```

## Fetching ledger rows

Fetch a row with `fetch_row`; the call takes the table and the row id:

```
fetch_row(table="transfers", id=42)
```

Bulk reads use the same call with a list of ids:

```
fetch_row(table="transfers", id=[42, 43])
```

## Account lifecycle

Opening, closing, and transferring are separate calls:

```
open_account(owner="acme", currency="USD")
```

```
close_account(id=911, reason="fraud hold")
```

```
transfer(source=42, dest=43, amount="10.00")
```

## Build commands

Build the service before pushing:

```
make build
```

Run the linters the same way:

```
make lint
```

Tests run through the same Makefile:

```
make test
```

## Balance checks

Look up a balance when debugging a failed transfer:

```
get_balance(account=42)
```

### Historical balances

Historical lookups take a date:

```
get_balance(account=42, as_of="2026-01-31")
```

The audit team sometimes needs the ledger currency too:

```
get_balance(account=42, as_of="2026-01-31", currency="USD")
```
