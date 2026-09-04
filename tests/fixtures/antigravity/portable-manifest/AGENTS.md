# Routeboard

Route-planning helpers packaged once and installed by several agents. The
package under `.agents/plugins/route-kit/` is written to the portable Agent
Plugins schema; Antigravity loads it from that location unchanged.

## Build and test

- `make test` runs the unit suite.
- `make package` builds the distributable archive from the same directory
  Antigravity reads in place.
