---
description: Fetch data from a configured API endpoint
argument-hint: "<endpoint-name> [--format json|csv]"
---

## Name
data-fetcher:fetch

## Synopsis
```
/data-fetcher:fetch users --format json
```

## Description
Retrieves data from a pre-configured API endpoint and returns it in the
requested format. Supports both REST and GraphQL endpoints defined in
the project configuration.

## Implementation
1. Look up the endpoint configuration by name
2. Construct the HTTP request with authentication headers
3. Execute the request and handle pagination if needed
4. Transform the response into the requested output format
5. Return the formatted data to the user
