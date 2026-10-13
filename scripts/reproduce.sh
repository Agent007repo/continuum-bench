#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
make setup test analyze docs report
