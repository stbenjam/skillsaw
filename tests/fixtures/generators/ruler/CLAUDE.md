

<!-- Source: .ruler/AGENTS.md -->

# Inventory service

The service records warehouse stock and reservation events.

## Development

You should consider adding a regression test when changing reservation logic.
Use the existing database transaction when updating a reservation.



<!-- Source: .ruler/backend/api.md -->

# HTTP API

Return a stable error code when a reservation cannot be fulfilled.
Keep the authorization check before the stock lookup.
