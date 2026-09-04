# Search service

A Go service fronting the product catalog index. Run `make test` before
pushing; the integration suite needs a local OpenSearch, which
`make services-up` starts.

Long-lived operational knowledge lives in `.agents/memory/` so it survives
the session that learned it.
