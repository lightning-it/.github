#!/usr/bin/env bash
# Exact-controller guard executed only inside the digest-pinned Devtools image.
set -Eeuo pipefail
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_NOSYSTEM=1
export GIT_TERMINAL_PROMPT=0
export LC_ALL=C

readonly CONTROLLER_PATH="scripts/release-promotion-preflight.sh"

[[ "${ADMITTED_CONTROLLER_BLOB}" =~ ^[0-9a-f]{40}$ ]]
controller_entry="$(git ls-tree "${RUN_SHA}" -- "${CONTROLLER_PATH}")"
test "${controller_entry}" = \
  "100644 blob ${ADMITTED_CONTROLLER_BLOB}"$'\t'"${CONTROLLER_PATH}"
test -f "${CONTROLLER_PATH}" && test ! -L "${CONTROLLER_PATH}"
test "$(git hash-object -- "${CONTROLLER_PATH}")" = \
  "${ADMITTED_CONTROLLER_BLOB}"

exec bash "${CONTROLLER_PATH}"
