#!/bin/sh
# Seed the shared boundary-cache volume with the boundary files bundled in the image
# (never overwrites files already there), then run the service command.
set -e
if [ -n "$EARTHSCOPE_BOUNDARY_CACHE_DIR" ] && [ -d /app/app/data/boundary_cache ]; then
  mkdir -p "$EARTHSCOPE_BOUNDARY_CACHE_DIR"
  for f in /app/app/data/boundary_cache/*; do
    [ -e "$f" ] || continue
    [ -e "$EARTHSCOPE_BOUNDARY_CACHE_DIR/$(basename "$f")" ] || cp "$f" "$EARTHSCOPE_BOUNDARY_CACHE_DIR/"
  done
fi
exec "$@"
