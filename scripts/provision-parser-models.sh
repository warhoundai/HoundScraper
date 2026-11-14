#!/bin/sh
# Explicit network-enabled provisioning; runtime parser remains offline.
set -eu
# Read upstream model licenses before provisioning or redistributing weights.
docling-tools models download --output-dir /models
docling-tools models download whisper_tiny --output-dir /models
