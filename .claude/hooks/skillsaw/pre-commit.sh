#!/usr/bin/env bash
set -euo pipefail

make update 2>&1 || { echo "BLOCKED: make update failed"; exit 2; }
make test   2>&1 || { echo "BLOCKED: make test failed";   exit 2; }

