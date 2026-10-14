#!/usr/bin/env bash
# Protected orchestration only; every policy workload runs in pinned Devtools.
set -euo pipefail
case "${1:-}" in preflight|approve|verify|invalidate) ;; *) exit 1 ;; esac
[ "$#" -eq 1 ]
[ "${GITHUB_ACTIONS:-}" = true ]
[ "${REPOSITORY:-}" = lightning-it/.github ]
policy_mode="$1"
cd "$(dirname "$0")/.."

policy_environment=()
for policy_name in GH_TOKEN GITHUB_API_URL GITHUB_RUN_ATTEMPT GITHUB_RUN_ID \
  REPOSITORY PR_NUMBER WORKFLOW_REF WORKFLOW_SHA LI219_EVENT_MODE \
  EVENT_UPDATED_AT EVENT_TITLE_JSON EVENT_BODY_JSON EVENT_LABELS_JSON \
  EVENT_ACTION EVENT_BASE EVENT_HEAD EVENT_HEAD_REPOSITORY \
  EVENT_HEAD_REPOSITORY_OWNER EVENT_HEAD_REF EVENT_BASE_REF EVENT_AUTHOR \
  EVENT_AUTHOR_TYPE EVENT_SENDER APPROVAL_BINDING APPROVAL_REUSE_RUN; do
  policy_environment+=("$policy_name=${!policy_name:-}")
done

run_policy() {
  # The quoted program expands its mode only inside the protected container.
  # shellcheck disable=SC2016
  env -i PATH="$PATH" HOME="$HOME" GITHUB_ACTIONS=true \
    WUNDER_CONTAINER_ENGINE=docker WUNDER_DEVTOOLS_NETWORK=bridge \
    WUNDER_DEVTOOLS_RUN_AS_HOST_UID=1 \
    bash scripts/wunder-devtools-ee.sh env "${policy_environment[@]}" \
      GITHUB_OUTPUT=/tmp/wunder/policy-output \
      bash -c 'set -euo pipefail; python3 scripts/dot-github-policy-approval.py "$1";
        if [ "$1" = preflight ]; then cat /tmp/wunder/policy-output; fi' policy "$policy_mode"
}
if [ "$policy_mode" = preflight ]; then
  # Only the successful protected container's two admission outputs reach Actions.
  policy_outputs="$(run_policy)"
  printf '%s\n' "$policy_outputs" >>"${GITHUB_OUTPUT:?}"
else
  run_policy
fi
