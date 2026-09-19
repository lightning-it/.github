#!/usr/bin/env bash
# Exact-controller guard executed only inside the digest-pinned Devtools image.
set -Eeuo pipefail
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_NOSYSTEM=1
export GIT_TERMINAL_PROMPT=0
export LC_ALL=C

readonly CONTROLLER_PATH="scripts/release-promotion-preflight.sh"

fail_closed() {
  printf '::error::%s\n' "${1}" >&2
  exit 1
}

[[ "${RUN_SHA:-}" =~ ^[0-9a-f]{40}$ ]] \
  || fail_closed "The revalidation revision is malformed."
[[ "${ADMITTED_CONTROLLER_BLOB:-}" =~ ^[0-9a-f]{40}$ ]] \
  || fail_closed "The admitted controller blob is malformed."
controller_entry="$(git ls-tree "${RUN_SHA}" -- "${CONTROLLER_PATH}")" \
  || fail_closed "The admitted controller tree entry is unreadable."
[ "${controller_entry}" = \
  "100644 blob ${ADMITTED_CONTROLLER_BLOB}"$'\t'"${CONTROLLER_PATH}" ] \
  || fail_closed "The admitted controller tree binding does not match."
[ -f "${CONTROLLER_PATH}" ] && [ ! -L "${CONTROLLER_PATH}" ] \
  || fail_closed "The local controller is not a regular non-symlink file."
controller_blob="$(git hash-object -- "${CONTROLLER_PATH}")" \
  || fail_closed "The local controller bytes are unreadable."
[ "${controller_blob}" = "${ADMITTED_CONTROLLER_BLOB}" ] \
  || fail_closed "The local controller bytes do not match the admitted blob."

exec bash "${CONTROLLER_PATH}"
