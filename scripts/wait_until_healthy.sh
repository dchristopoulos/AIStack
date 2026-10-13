#!/bin/sh
# Wait for a container's own HEALTHCHECK to pass, so CI exercises the check the image ships.
#   scripts/wait_until_healthy.sh <container name>
set -eu

container="$1"

for _ in $(seq 1 60); do
    status="$(docker inspect --format '{{.State.Health.Status}}' "$container")"
    if [ "$status" = "healthy" ]; then
        exit 0
    fi
    if [ "$(docker inspect --format '{{.State.Running}}' "$container")" != "true" ]; then
        echo "Container '$container' stopped before becoming healthy." >&2
        docker logs "$container" >&2
        exit 1
    fi
    sleep 1
done

echo "Container '$container' was still '$status' after 60 seconds." >&2
docker logs "$container" >&2
exit 1
