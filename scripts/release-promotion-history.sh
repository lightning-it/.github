#!/usr/bin/env bash
# Read-only promotion-history classifier. It never creates, updates, or closes a PR.
set -Eeuo pipefail
export LC_ALL=C

readonly EXPECTED_REPOSITORY="lightning-it/.github"
readonly EXPECTED_TITLE="chore(release): promote develop to main"
readonly HARD_MAX_BYTES=67108864
readonly HARD_MAX_DEADLINE_SECONDS=300
readonly HARD_MAX_PAGES=1000
readonly HARD_MAX_RECORDS=10000

disposition="blocked"
history_sha256=""
pr_number=""
reported=false
history_file=""
history_bytes=0
history_pages=0
history_records=0

cleanup() {
  if [ -n "${history_file}" ] && [ -f "${history_file}" ]; then
    rm -f -- "${history_file}"
  fi
}

report_disposition() {
  local next_disposition="${1}"
  disposition="${next_disposition}"
  {
    printf 'disposition=%s\n' "${disposition}"
    printf 'history_sha256=%s\n' "${history_sha256}"
    printf 'pr_number=%s\n' "${pr_number}"
  } >>"${GITHUB_OUTPUT}"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '{"disposition":"%s","history_sha256":"%s","pr_number":"%s"}\n' \
      "${disposition}" "${history_sha256}" "${pr_number}" \
      >>"${GITHUB_STEP_SUMMARY}"
  fi
  reported=true
}

on_error() {
  local status=$?
  trap - ERR
  if [ "${reported}" != true ] && [ -n "${GITHUB_OUTPUT:-}" ]; then
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
    || fail_closed "RUNNER_TEMP is required for promotion history admission."
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

trap cleanup EXIT
trap on_error ERR
umask 077

for command_name in awk gh head jq mktemp rm sha256sum stat timeout wc; do
  command -v "${command_name}" >/dev/null \
    || fail_closed "${command_name} is required for promotion history admission."
done

[ "${REPOSITORY}" = "${EXPECTED_REPOSITORY}" ] \
  || fail_closed "Promotion history is bound to the protected repository."
[[ "${EXPECTED_BASE_SHA}" =~ ^[0-9a-f]{40}$ ]] \
  || fail_closed "The admitted protected base is malformed."
[[ "${EXPECTED_HEAD_SHA}" =~ ^[0-9a-f]{40}$ ]] \
  || fail_closed "The admitted protected head is malformed."
[[ "${OPERATION_KEY:-}" =~ ^[0-9a-f]{64}$ ]] \
  || fail_closed "The operation key is malformed."
[[ "${OWNER_RUN_ID:-}" =~ ^[1-9][0-9]*$ ]] \
  || fail_closed "The owner run ID is malformed."
[ "${OWNER_RUN_ATTEMPT:-}" = 1 ] \
  || fail_closed "Promotion history is restricted to exact attempt 1."
[[ "${HISTORY_MAX_BYTES:-}" =~ ^[1-9][0-9]*$ ]] \
  && [ "${HISTORY_MAX_BYTES}" -le "${HARD_MAX_BYTES}" ] \
  || fail_closed "The history byte bound is malformed or unsafe."
[[ "${HISTORY_MAX_PAGES:-}" =~ ^[1-9][0-9]*$ ]] \
  && [ "${HISTORY_MAX_PAGES}" -le "${HARD_MAX_PAGES}" ] \
  || fail_closed "The history page bound is malformed or unsafe."
[[ "${HISTORY_MAX_RECORDS:-}" =~ ^[1-9][0-9]*$ ]] \
  && [ "${HISTORY_MAX_RECORDS}" -le "${HARD_MAX_RECORDS}" ] \
  || fail_closed "The history record bound is malformed or unsafe."
[[ "${HISTORY_DEADLINE_SECONDS:-}" =~ ^[1-9][0-9]*$ ]] \
  && [ "${HISTORY_DEADLINE_SECONDS}" -le "${HARD_MAX_DEADLINE_SECONDS}" ] \
  || fail_closed "The history deadline is malformed or unsafe."
[ -n "${GH_TOKEN:-}" ] \
  || fail_closed "A read-capable GitHub token is required for history admission."
[ -n "${GITHUB_OUTPUT:-}" ] \
  || fail_closed "Promotion history requires a GitHub output path."
validate_runner_temp

history_file="$(mktemp "${RUNNER_TEMP}/promotion-history.XXXXXX")"
set +o pipefail
timeout "${HISTORY_DEADLINE_SECONDS}" \
  gh api --paginate --slurp \
  "repos/${REPOSITORY}/pulls?state=all&per_page=100" \
  | head -c "$((HISTORY_MAX_BYTES + 1))" >"${history_file}"
fetch_status=("${PIPESTATUS[@]}")
set -o pipefail
history_bytes="$(wc -c <"${history_file}")"
[ "${history_bytes}" -le "${HISTORY_MAX_BYTES}" ] \
  || fail_closed "The promotion history exceeds its raw-byte bound."
[ "${fetch_status[0]}" -eq 0 ] \
  || fail_closed "The promotion pull-request history is unavailable or timed out."
[ "${fetch_status[1]}" -eq 0 ] \
  || fail_closed "The promotion history byte limiter failed."

jq -e '
  type == "array"
  and length >= 1
  and all(.[]; type == "array")
  and all(.[][]; type == "object")
' "${history_file}" >/dev/null \
  || fail_closed "The promotion history pagination envelope is malformed."
history_pages="$(jq -r 'length' "${history_file}")"
history_records="$(jq -r '[.[][]] | length' "${history_file}")"
[ "${history_pages}" -le "${HISTORY_MAX_PAGES}" ] \
  || fail_closed "The promotion history exceeds its page bound."
[ "${history_records}" -le "${HISTORY_MAX_RECORDS}" ] \
  || fail_closed "The promotion history exceeds its record bound."

head_marker="<!-- lit-promotion-head:${EXPECTED_HEAD_SHA} -->"
operation_marker="<!-- lit-promotion-operation:${OPERATION_KEY} -->"
run_marker="<!-- lit-promotion-run:${OWNER_RUN_ID}:${OWNER_RUN_ATTEMPT} -->"
# shellcheck disable=SC2016  # jq variables must remain literal for jq.
relevant_history="$(jq -Sc \
  --arg head "${EXPECTED_HEAD_SHA}" \
  --arg marker "${head_marker}" \
  --arg repository "${REPOSITORY}" '
    def body_lines:
      if ((.body // "") | type) == "string"
      then ((.body // "") | split("\n"))
      else []
      end;
    [
      .[][]
      | select(
          .base.repo.full_name == $repository
          and .head.repo.full_name == $repository
          and (
            (
              .state == "open"
              and .base.ref == "main"
              and .head.ref == "develop"
            )
            or .head.sha == $head
            or ((body_lines | index($marker)) != null)
          )
        )
      | {
          number,
          state,
          merged_at,
          draft,
          title,
          user: .user.login,
          base_repo: .base.repo.full_name,
          base_ref: .base.ref,
          base_sha: .base.sha,
          head_repo: .head.repo.full_name,
          head_ref: .head.ref,
          head_sha: .head.sha,
          body: (.body // "")
        }
    ]
    | sort_by(.number)
  ' "${history_file}")" \
  || fail_closed "The relevant promotion history could not be normalized."

history_sha256="$(
  printf '%s\n' "${relevant_history}" | sha256sum | awk '{ print $1 }'
)"
[[ "${history_sha256}" =~ ^[0-9a-f]{64}$ ]] \
  || fail_closed "The promotion history digest is malformed."

# shellcheck disable=SC2016  # jq variables must remain literal for jq.
classification="$(jq -ce \
  --arg base "${EXPECTED_BASE_SHA}" \
  --arg head "${EXPECTED_HEAD_SHA}" \
  --arg head_marker "${head_marker}" \
  --arg operation_marker "${operation_marker}" \
  --arg repository "${REPOSITORY}" \
  --arg run_marker "${run_marker}" \
  --arg title "${EXPECTED_TITLE}" '
    def lines:
      if (.body | type) == "string"
      then (.body | split("\n"))
      else error("promotion body is not a string")
      end;
    def head_markers:
      [lines[] | select(startswith("<!-- lit-promotion-head:"))];
    def run_markers:
      [lines[] | select(startswith("<!-- lit-promotion-run:"))];
    def operation_markers:
      [lines[] | select(startswith("<!-- lit-promotion-operation:"))];
    def dispatch_markers:
      [lines[] | select(startswith("<!-- lit-promotion-dispatch-"))];
    def dispatch_binding:
      dispatch_markers as $markers
      | if ($markers | length) != 1
        then error("promotion dispatch marker count is not one")
        else $markers[0] | capture(
          "^<!-- lit-promotion-dispatch-"
          + "(?<state>pending|failed|succeeded):"
          + "(?<base>[0-9a-f]{40}):(?<head>[0-9a-f]{40}) -->$"
        )
        end;
    if length == 0 then
      {disposition: "mutate", pr_number: null}
    elif length != 1 then
      error("promotion history is ambiguous")
    else
      .[0] as $promotion
      | ($promotion | head_markers) as $heads
      | ($promotion | run_markers) as $runs
      | ($promotion | operation_markers) as $operations
      | ($promotion | dispatch_binding) as $dispatch
      | if (
          ($promotion.number | type == "number" and . > 0 and floor == .)
          and $promotion.user == "lightning-it-release-automation[bot]"
          and $promotion.base_repo == $repository
          and $promotion.head_repo == $repository
          and $promotion.base_ref == "main"
          and $promotion.head_ref == "develop"
          and ($promotion.base_sha | type == "string")
          and ($promotion.base_sha | test("^[0-9a-f]{40}$"))
          and $promotion.head_sha == $head
          and $promotion.draft == false
          and $promotion.title == $title
          and $heads == [$head_marker]
          and $operations == [$operation_marker]
          and $runs == [$run_marker]
          and $dispatch.head == $head
          and $dispatch.base == $promotion.base_sha
        ) | not then
          error("promotion history is not an exact controller record")
        elif (
          $promotion.state == "open"
          and $promotion.merged_at == null
          and $promotion.base_sha == $base
          and $dispatch.base == $base
          and $dispatch.state == "succeeded"
        ) then
          {disposition: "active", pr_number: $promotion.number}
        elif (
          $promotion.state == "closed"
          and (
            $promotion.merged_at == null
            or ($promotion.merged_at | type) == "string"
          )
          and (
            $dispatch.state == "failed"
            or $dispatch.state == "succeeded"
          )
        ) then
          {disposition: "consumed", pr_number: $promotion.number}
        else
          error("promotion history state is not handled")
        end
    end
  ' <<<"${relevant_history}")" \
  || fail_closed "Promotion history is ambiguous, malformed, or unhandled."

disposition="$(jq -r .disposition <<<"${classification}")"
pr_number="$(jq -r '.pr_number // ""' <<<"${classification}")"
case "${disposition}" in
  mutate)
    [ -z "${pr_number}" ] \
      || fail_closed "Mutation admission unexpectedly selected a pull request."
    ;;
  active | consumed)
    [[ "${pr_number}" =~ ^[1-9][0-9]*$ ]] \
      || fail_closed "The classified promotion number is malformed."
    ;;
  *)
    fail_closed "The promotion history disposition is unsupported."
    ;;
esac

trap - ERR
report_disposition "${disposition}"
