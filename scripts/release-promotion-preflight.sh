#!/usr/bin/env bash
# Fail-closed release admission executed only in the digest-pinned Devtools image.
set -Eeuo pipefail
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_NOSYSTEM=1
export GIT_TERMINAL_PROMPT=0
export LC_ALL=C
unset GH_TOKEN GITHUB_TOKEN

readonly CONTROLLER_PATH="scripts/release-promotion-preflight.sh"
readonly REVALIDATOR_PATH="scripts/release-promotion-preflight-revalidate.sh"
readonly BINDER_PATH="scripts/release-promotion-preflight-bind.sh"
readonly HISTORY_PATH="scripts/release-promotion-history.sh"
readonly WORKFLOW_PATH=".github/workflows/reconcile-develop-to-main.yml"
readonly LEGACY_WORKFLOW_PATH=".github/workflows/promote-develop-to-main.yml"
readonly TEMPORARY_WORKFLOW_PATH=".github/workflows/release-promotion-maintenance-lock.yml"
readonly CUTOVER_PROBE_PATH=".github/workflows/release-promotion-credential-tombstone-probe.yml"
readonly CUTOVER_PROBE_SCRIPT_PATH="scripts/release-promotion-credential-tombstone-probe.sh"
readonly LOCK_PATH=".lit/release-promotion-admission.json"
readonly EXPECTED_REPOSITORY="lightning-it/.github"
readonly EXPECTED_REF="refs/heads/develop"

disposition="blocked"
stage_id="invalid"
base_sha=""
head_sha=""
integration_tree=""
projection_sha256=""
promotion_patch_bytes=""
promotion_patch_sha256=""
promotion_patch_format=""
controller_blob=""
reported=false
review_file=""
projection_file=""
projection_listing_file=""

cleanup() {
  local temporary_file
  for temporary_file in \
    "${review_file}" \
    "${projection_file}" \
    "${projection_listing_file}"
  do
    if [ -n "${temporary_file}" ] && [ -f "${temporary_file}" ]; then
      rm -f -- "${temporary_file}"
    fi
  done
}

report_disposition() {
  local next_disposition="${1}"
  local payload
  disposition="${next_disposition}"
  payload="$(
    jq -cn \
      --arg disposition "${disposition}" \
      --arg stage "${stage_id}" \
      --arg base_sha "${base_sha}" \
      --arg head_sha "${head_sha}" \
      --arg integration_tree "${integration_tree}" \
      --arg projection_sha256 "${projection_sha256}" \
      --arg promotion_patch_bytes "${promotion_patch_bytes}" \
      --arg promotion_patch_sha256 "${promotion_patch_sha256}" \
      --arg promotion_patch_format "${promotion_patch_format}" \
      --arg controller_blob "${controller_blob}" '
        {
          schema_version: 1,
          disposition: $disposition,
          stage: $stage,
          base_sha: $base_sha,
          head_sha: $head_sha,
          integration_tree: $integration_tree,
          projection_sha256: $projection_sha256,
          promotion_patch_bytes: (
            if ($promotion_patch_bytes | test("^[0-9]+$"))
            then ($promotion_patch_bytes | tonumber)
            else null
            end
          ),
          promotion_patch_sha256: $promotion_patch_sha256,
          promotion_patch_format: $promotion_patch_format,
          develop_patch_bytes: null,
          develop_patch_sha256: "",
          develop_patch_format: "",
          controller_blob: $controller_blob,
          unlock_candidate_sha: ""
        }
      '
  )"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '%s\n' "${payload}" >>"${GITHUB_STEP_SUMMARY}"
  fi
  {
    printf 'disposition=%s\n' "${disposition}"
    printf 'stage=%s\n' "${stage_id}"
    printf 'base_sha=%s\n' "${base_sha}"
    printf 'head_sha=%s\n' "${head_sha}"
    printf 'integration_tree=%s\n' "${integration_tree}"
    printf 'projection_sha256=%s\n' "${projection_sha256}"
    printf 'promotion_patch_bytes=%s\n' "${promotion_patch_bytes}"
    printf 'promotion_patch_sha256=%s\n' "${promotion_patch_sha256}"
    printf 'promotion_patch_format=%s\n' "${promotion_patch_format}"
    printf 'develop_patch_bytes=\n'
    printf 'develop_patch_sha256=\n'
    printf 'develop_patch_format=\n'
    printf 'controller_blob=%s\n' "${controller_blob}"
    printf 'unlock_candidate_sha=\n'
  } >>"${GITHUB_OUTPUT}"
  reported=true
}

on_error() {
  local status=$?
  trap - ERR
  if [ "${reported}" != true ]; then
    report_disposition blocked
  fi
  exit "${status}"
}

fail_closed() {
  printf '::error::%s\n' "${1}" >&2
  return 1
}

validate_runner_temp() {
  local mode
  [ -n "${RUNNER_TEMP:-}" ] \
    || fail_closed "RUNNER_TEMP is required for release admission."
  [[ "${RUNNER_TEMP}" = /* ]] \
    || fail_closed "RUNNER_TEMP must be an absolute directory."
  [ -d "${RUNNER_TEMP}" ] \
    && [ ! -L "${RUNNER_TEMP}" ] \
    && [ -O "${RUNNER_TEMP}" ] \
    && [ -w "${RUNNER_TEMP}" ] \
    && [ -x "${RUNNER_TEMP}" ] \
    || fail_closed "RUNNER_TEMP must be an owned, writable, searchable real directory."
  mode="$(stat -c '%a' -- "${RUNNER_TEMP}")" \
    || fail_closed "RUNNER_TEMP permissions are unreadable."
  [[ "${mode}" =~ ^[0-7]{1,2}[0145][0145]$ ]] \
    || fail_closed "RUNNER_TEMP must not be group- or world-writable."
}

reject_persisted_git_credentials() {
  local credential_config config_status
  if credential_config="$(
    git config --local --name-only --get-regexp \
      '^(credential(\..*)?\.helper|http(\..*)?\.extraheader)$'
  )"; then
    :
  else
    config_status=$?
    [ "${config_status}" -eq 1 ] \
      || fail_closed "The local Git credential configuration is unreadable."
    credential_config=""
  fi
  [ -z "${credential_config}" ] \
    || fail_closed "Anonymous release admission rejects persisted Git credentials."
}

bind_regular_file() {
  local commit="${1}"
  local path="${2}"
  local entry metadata name mode type blob unexpected
  entry="$(git ls-tree "${commit}" -- "${path}")"
  metadata="${entry%%$'\t'*}"
  name="${entry#*$'\t'}"
  read -r mode type blob unexpected <<<"${metadata}"
  [ -z "${unexpected:-}" ] \
    && [ "${mode}" = 100644 ] \
    && [ "${type}" = blob ] \
    && [[ "${blob}" =~ ^[0-9a-f]{40}$ ]] \
    && [ "${name}" = "${path}" ] \
    && [ -f "${path}" ] \
    && [ ! -L "${path}" ] \
    && [ "$(git hash-object -- "${path}")" = "${blob}" ] \
    || fail_closed "A release control file is absent, unsafe, or drifted."
  printf '%s\n' "${blob}"
}

projection_digest() {
  local commit="${1}"
  local entry metadata mode name object type unexpected
  projection_listing_file="$(mktemp "${RUNNER_TEMP}/promotion-tree.XXXXXX")"
  projection_file="$(mktemp "${RUNNER_TEMP}/promotion-projection.XXXXXX")"
  git ls-tree -r -z --full-tree "${commit}" >"${projection_listing_file}" \
    || fail_closed "The repository projection could not be enumerated."
  while IFS= read -r -d '' entry; do
    metadata="${entry%%$'\t'*}"
    name="${entry#*$'\t'}"
    read -r mode type object unexpected <<<"${metadata}"
    if [ -n "${unexpected:-}" ] \
      || { [ "${mode}" != 100644 ] && [ "${mode}" != 100755 ]; } \
      || [ "${type}" != blob ] \
      || ! [[ "${object}" =~ ^[0-9a-f]{40}$ ]] \
      || [ -z "${name}" ]; then
      rm -f -- "${projection_listing_file}" "${projection_file}"
      projection_listing_file=""
      projection_file=""
      fail_closed "The repository projection contains an unsafe tree entry."
      return 1
    fi
    printf '%s\0' "${entry}" >>"${projection_file}"
  done <"${projection_listing_file}"
  sha256sum "${projection_file}" | LC_ALL=C awk '{ print $1 }'
  rm -f -- "${projection_listing_file}" "${projection_file}"
  projection_listing_file=""
  projection_file=""
}

reject_unsafe_delta() {
  local old_revision="${1}"
  local new_revision="${2}"
  local name_status numstat raw_delta
  raw_delta="$(git diff --raw --no-renames \
    "${old_revision}" "${new_revision}" --)"
  if awk '
      $1 ~ /^:(120000|160000)$/ || $2 ~ /^(120000|160000)$/ {
        unsafe = 1
      }
      END { exit unsafe ? 0 : 1 }
    ' <<<"${raw_delta}"
  then
    fail_closed "Release admission rejects symlink or submodule changes."
    return 1
  fi
  name_status="$(git diff --name-status --find-renames \
    "${old_revision}" "${new_revision}" --)"
  if grep -Eq '^R[0-9]*[[:space:]]' <<<"${name_status}"; then
    fail_closed "Release admission rejects rename changes."
    return 1
  fi
  numstat="$(git diff --numstat --no-renames \
    "${old_revision}" "${new_revision}" --)"
  if awk -F '\t' '
      $1 == "-" || $2 == "-" { binary = 1 }
      END { exit binary ? 0 : 1 }
    ' <<<"${numstat}"
  then
    fail_closed "Release admission rejects binary changes."
    return 1
  fi
}

[ -n "${GITHUB_OUTPUT:-}" ] \
  || fail_closed "Release admission requires a GitHub output path."

trap cleanup EXIT
trap on_error ERR
umask 077

for command_name in awk git grep jq mktemp rm sha256sum stat tr wc; do
  command -v "${command_name}" >/dev/null \
    || fail_closed "${command_name} is required for release admission."
done

[ "${REPOSITORY}" = "${EXPECTED_REPOSITORY}" ] \
  || fail_closed "Release admission is bound to the protected repository."
[ "${REF}" = "${EXPECTED_REF}" ] \
  || fail_closed "Release admission is bound to the protected develop ref."
[ "${REF_PROTECTED}" = true ] \
  || fail_closed "Release admission requires the protected develop ref."
[ "${RUN_ATTEMPT}" = 1 ] \
  || fail_closed "Release admission rejects workflow re-runs."
[ "${EVENT_NAME}" = push ] \
  || fail_closed "Release admission requires a protected develop push."
[[ "${RUN_SHA}" =~ ^[0-9a-f]{40}$ ]] \
  || fail_closed "The workflow revision is malformed."
test -z "$(git status --porcelain=v1 --untracked-files=all)" \
  || fail_closed "The release admission worktree is not exact."
validate_runner_temp

reject_persisted_git_credentials
git fetch --quiet --no-tags origin \
  +refs/heads/main:refs/remotes/origin/main \
  +refs/heads/develop:refs/remotes/origin/develop \
  || fail_closed "The protected refs could not be refreshed anonymously."
base_sha="$(git rev-parse refs/remotes/origin/main)"
head_sha="$(git rev-parse refs/remotes/origin/develop)"
[ "${RUN_SHA}" = "${head_sha}" ] \
  && [ "$(git rev-parse HEAD)" = "${head_sha}" ] \
  || fail_closed "The checked-out revision is not live protected develop."
git merge-base --is-ancestor "${base_sha}" "${head_sha}" \
  || fail_closed "Develop does not contain the protected main ancestry."

controller_blob="$(bind_regular_file "${head_sha}" "${CONTROLLER_PATH}")"
bind_regular_file "${head_sha}" "${REVALIDATOR_PATH}" >/dev/null
bind_regular_file "${head_sha}" "${BINDER_PATH}" >/dev/null
bind_regular_file "${head_sha}" "${HISTORY_PATH}" >/dev/null
bind_regular_file "${head_sha}" "${WORKFLOW_PATH}" >/dev/null
for absent_path in \
  "${LEGACY_WORKFLOW_PATH}" \
  "${TEMPORARY_WORKFLOW_PATH}" \
  "${CUTOVER_PROBE_PATH}" \
  "${CUTOVER_PROBE_SCRIPT_PATH}" \
  "${LOCK_PATH}"
do
  if git cat-file -e "${head_sha}:${absent_path}" 2>/dev/null \
    || [ -e "${absent_path}" ]; then
    fail_closed "A retired or temporary release control path is present."
  fi
done

integration_tree="$(git merge-tree --write-tree "${base_sha}" "${head_sha}")" \
  || fail_closed "The protected promotion does not merge cleanly."
[ "${integration_tree}" = "$(git rev-parse "${head_sha}^{tree}")" ] \
  || fail_closed "The protected merge tree differs from develop."
reject_unsafe_delta "${base_sha}" "${head_sha}"

review_file="$(mktemp "${RUNNER_TEMP}/promotion-review.XXXXXX")"
git diff \
  --binary \
  --full-index \
  --no-renames \
  --no-color \
  --no-ext-diff \
  --no-textconv \
  "${base_sha}^{tree}" "${integration_tree}" -- >"${review_file}"
promotion_patch_bytes="$(
  LC_ALL=C wc -c <"${review_file}" | LC_ALL=C tr -d '[:space:]'
)"
[[ "${promotion_patch_bytes}" =~ ^[0-9]+$ ]] \
  || fail_closed "The protected promotion patch size is malformed."
if grep -Eq '^(GIT binary patch|Binary files )' "${review_file}"; then
  fail_closed "The canonical promotion review contains binary content."
fi
promotion_patch_sha256="$(sha256sum "${review_file}" | awk '{ print $1 }')"
promotion_patch_format="git-diff-binary-full-index-no-renames-v1"
rm -f -- "${review_file}"
review_file=""
projection_sha256="$(projection_digest "${head_sha}")"

if [ "${promotion_patch_bytes}" -eq 0 ]; then
  stage_id="no-content-delta"
  trap - ERR
  report_disposition noop
  exit 0
fi

changed_paths_text="$(git diff --name-only --no-renames \
  "${base_sha}" "${head_sha}" --)" \
  || fail_closed "The protected path delta could not be enumerated."
changed_paths=()
if [ -n "${changed_paths_text}" ]; then
  mapfile -t changed_paths <<<"${changed_paths_text}"
fi
if [ "${#changed_paths[@]}" -eq 1 ] \
  && [ "${changed_paths[0]}" = .lit/main-ancestry.json ]; then
  parents="$(git show -s --format=%P "${head_sha}")" \
    || fail_closed "The protected develop tip is unreadable."
  read -r develop_parent ancestry_merge unexpected_parent <<<"${parents}"
  [ -n "${develop_parent}" ] \
    && [ -n "${ancestry_merge}" ] \
    && [ -z "${unexpected_parent:-}" ] \
    || fail_closed \
      "The ancestry-only delta is not a two-parent protected PR merge."
  ancestry_parents="$(git show -s --format=%P "${ancestry_merge}")" \
    || fail_closed "The protected ancestry merge is unreadable."
  read -r inner_develop_parent inner_main_parent unexpected_inner_parent \
    <<<"${ancestry_parents}"
  [ -n "${inner_develop_parent}" ] \
    && [ -n "${inner_main_parent}" ] \
    && [ -z "${unexpected_inner_parent:-}" ] \
    || fail_closed \
      "The protected ancestry merge does not have exactly two parents."
  evidence="$(git show "${head_sha}:.lit/main-ancestry.json")" \
    || fail_closed "The protected main-ancestry evidence is unreadable."
  jq -e \
    --arg repository "${REPOSITORY}" \
    --arg main_sha "${base_sha}" \
    --arg develop_parent_sha "${develop_parent}" '
      (keys | sort) == [
        "develop_parent_sha",
        "main_sha",
        "purpose",
        "repository",
        "schema_version"
      ]
      and .schema_version == 1
      and .repository == $repository
      and .main_sha == $main_sha
      and .develop_parent_sha == $develop_parent_sha
      and .purpose == "Bind the reviewed main ancestry backmerge."
    ' <<<"${evidence}" >/dev/null \
    || fail_closed \
      "The ancestry-only delta does not match the protected contract."
  [ "${inner_develop_parent}" = "${develop_parent}" ] \
    && [ "${inner_main_parent}" = "${base_sha}" ] \
    || fail_closed "The protected ancestry parent binding is invalid."
  stage_id="ancestry-only-backmerge"
  trap - ERR
  report_disposition noop
  exit 0
fi
[ "${promotion_patch_bytes}" -lt 200000 ] \
  || fail_closed "The protected promotion patch exceeds 199999 bytes."

stage_id="bounded-release-plan"
trap - ERR
report_disposition release
