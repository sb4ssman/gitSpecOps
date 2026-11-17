#!/bin/sh
# macOS: double-click this in Finder and it opens in Terminal and runs setup (run_setup.sh).
cd "$(dirname "$0")" && exec ./run_setup.sh "$@"
