#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Tesla Intelligence Core updater preserves /etc/ghost-tesla-ai and /var/lib/ghost-tesla-ai."
exec bash "$ROOT/install.sh"
