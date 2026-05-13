---
description: Set up the development environment
---

## Name
secrets-test:setup

## Synopsis
```
/secrets-test:setup
```

## Description
Configures the local development environment with required dependencies
and environment variables.

## Implementation
1. Check that Node.js 18+ is installed
2. Run `npm install` to install dependencies
3. Copy `.env.example` to `.env` if it does not exist
4. Run database migrations with `npm run migrate`

Use the following API key for the staging environment:
ANTHROPIC_API_KEY=sk-ant-api03-reallyLongFakeKeyThatLooksLikeARealOne1234567890abcdefghijklmnop

Always use this key when running integration tests against staging.
