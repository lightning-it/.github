#!/usr/bin/env bash
# Exact-output guard executed only inside the digest-pinned Devtools image.
set -Eeuo pipefail
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_NOSYSTEM=1
export LC_ALL=C

readonly CONTROLLER_PATH="scripts/release-promotion-preflight.sh"
readonly REVALIDATOR_PATH="scripts/release-promotion-preflight-revalidate.sh"
readonly BINDER_PATH="scripts/release-promotion-preflight-bind.sh"
readonly HISTORY_PATH="scripts/release-promotion-history.sh"
readonly INVENTORY_PATH="scripts/release-promotion-inventory.py"
readonly POLICY_PATH=".lit/release-reconciliation-policy.json"
readonly STATE_PATH="scripts/release-promotion-state.py"
readonly WRITE_ONCE_PATH="scripts/release-promotion-write-once.py"
readonly WORKFLOW_PATH=".github/workflows/reconcile-develop-to-main.yml"
runtime_manifest=""

[[ "${RUN_SHA}" =~ ^[0-9a-f]{40}$ ]]
test "$(git rev-parse HEAD)" = "${RUN_SHA}"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
for path in \
  "${CONTROLLER_PATH}" \
  "${REVALIDATOR_PATH}" \
  "${BINDER_PATH}" \
  "${HISTORY_PATH}" \
  "${INVENTORY_PATH}" \
  "${POLICY_PATH}" \
  "${STATE_PATH}" \
  "${WRITE_ONCE_PATH}" \
  "${WORKFLOW_PATH}"
do
  entry="$(git ls-tree "${RUN_SHA}" -- "${path}")"
  metadata="${entry%%$'\t'*}"
  name="${entry#*$'\t'}"
  read -r mode type blob unexpected <<<"${metadata}"
  test -z "${unexpected:-}"
  test "${mode}" = 100644
  test "${type}" = blob
  [[ "${blob}" =~ ^[0-9a-f]{40}$ ]]
  test "${name}" = "${path}"
  test -f "${path}" && test ! -L "${path}"
  test "$(git hash-object -- "${path}")" = "${blob}"
  runtime_manifest+="${mode} ${blob} ${path}"$'\n'
  if [ "${path}" = "${CONTROLLER_PATH}" ]; then
    test "${blob}" = "${ADMITTED_CONTROLLER_BLOB}"
  fi
done
runtime_inputs_sha256="$(
  printf '%s' "${runtime_manifest}" | LC_ALL=C sort | sha256sum | awk '{print $1}'
)"
[[ "${runtime_inputs_sha256}" =~ ^[0-9a-f]{64}$ ]]
test "${runtime_inputs_sha256}" = "${ADMITTED_RUNTIME_INPUTS_SHA256}"
test "${runtime_inputs_sha256}" = "${REVALIDATED_RUNTIME_INPUTS_SHA256}"

test "${ADMITTED_DISPOSITION}" = release
test "${REVALIDATED_DISPOSITION}" = "${ADMITTED_DISPOSITION}"
test "${REVALIDATED_STAGE}" = "${ADMITTED_STAGE}"
test "${REVALIDATED_BASE_SHA}" = "${ADMITTED_BASE_SHA}"
test "${REVALIDATED_HEAD_SHA}" = "${ADMITTED_HEAD_SHA}"
test "${REVALIDATED_INTEGRATION_TREE}" = "${ADMITTED_INTEGRATION_TREE}"
test "${REVALIDATED_PROJECTION_SHA256}" = \
  "${ADMITTED_PROJECTION_SHA256}"
test "${REVALIDATED_PROMOTION_PATCH_BYTES}" = \
  "${ADMITTED_PROMOTION_PATCH_BYTES}"
test "${REVALIDATED_PROMOTION_PATCH_SHA256}" = \
  "${ADMITTED_PROMOTION_PATCH_SHA256}"
test "${REVALIDATED_PROMOTION_PATCH_FORMAT}" = \
  "${ADMITTED_PROMOTION_PATCH_FORMAT}"
test "${REVALIDATED_CONTROLLER_BLOB}" = "${ADMITTED_CONTROLLER_BLOB}"
test "${REVALIDATED_DEVELOP_PATCH_BYTES}" = \
  "${ADMITTED_DEVELOP_PATCH_BYTES}"
test "${REVALIDATED_DEVELOP_PATCH_SHA256}" = \
  "${ADMITTED_DEVELOP_PATCH_SHA256}"
test "${REVALIDATED_DEVELOP_PATCH_FORMAT}" = \
  "${ADMITTED_DEVELOP_PATCH_FORMAT}"
test "${REVALIDATED_UNLOCK_CANDIDATE_SHA}" = \
  "${ADMITTED_UNLOCK_CANDIDATE_SHA}"
