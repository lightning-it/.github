#!/usr/bin/env bash
# Immutable common dispatcher. No candidate script receives the preparation token.
set -euo pipefail
umask 077
if [ "$#" -ne 2 ]; then
  echo 'Usage: run-common-quality.sh ABSOLUTE_CANDIDATE_CHECKOUT ABSOLUTE_PROTECTED_BASE' >&2
  exit 2
fi
source_root="$(cd "$(dirname "$0")/.." && pwd -P)"
candidate_root="$(cd "$1" && pwd -P)"
base_root="$(cd "$2" && pwd -P)"
case "$source_root$candidate_root$base_root" in *:*|*,*) exit 2 ;; esac
test "$source_root" != "$candidate_root"
test "$base_root" != "$candidate_root"
test -n "${GH_TOKEN:-}"
policy_directory="$(mktemp -d)"
dependency_directory="$(mktemp -d)"
mirror_directory="$(mktemp -d)"
trap 'rm -rf -- "$policy_directory" "$dependency_directory" "$mirror_directory"' EXIT
image='quay.io/l-it/ee-wunder-devtools-ubi9:v1.16.1@sha256:c5e8707e825fcddb3e7bbc7592ebdc99a02e6ba9fa2cad71b88bcd5c71bd4d08'
common=(--rm --read-only --cap-drop ALL --security-opt no-new-privileges=true
  --pids-limit 256 --cpus 2 --memory 2g --memory-swap 2g --user "$(id -u):$(id -g)"
  --tmpfs '/tmp:rw,nosuid,nodev,noexec,size=2g'
  --tmpfs '/tmp/wunder:rw,nosuid,nodev,exec,size=1g,mode=1777'
  -e HOME=/tmp/wunder -e TMPDIR=/tmp/wunder -e PYTHONDONTWRITEBYTECODE=1
  -e CHECKPOINT_DISABLE=1 -e TF_IN_AUTOMATION=1
  -v "$source_root:/source:ro")
# Source-only preparation: the candidate tree is not mounted into this container.
timeout -k 5s 300s docker run "${common[@]}" --network bridge \
  -e GH_TOKEN -e NATIVE_JOB -e GITHUB_REPOSITORY -e GITHUB_RUN_ID \
  -e NATIVE_PULL_NUMBER -e NATIVE_HEAD -e NATIVE_BASE -e GH_HOST=github.com \
  -v "$policy_directory:/out:rw" -w /source "$image" \
  python3 -I -B /source/scripts/workflow_common_quality.py prepare --policy /out/policy.json
terraform_mounts=()
if [ -f "$policy_directory/terraform-required" ]; then
  # Offline extraction emits only literal dependency coordinates/hashes. No
  # candidate code or comments enter the later network-enabled container.
  timeout -k 5s 120s docker run "${common[@]}" --network none \
    -v "$candidate_root:/workspace:ro" -v "$base_root:/protected-base:ro" \
    -v "$policy_directory/policy.json:/policy.json:ro" \
    -v "$dependency_directory:/dependency-output:rw" -w /workspace "$image" \
    python3 -I -B /source/scripts/workflow_terraform.py prepare \
    --policy /policy.json --base /protected-base --directory /dependency-output/inputs
  # No repository checkout, policy, token or private code is mounted here.
  timeout -k 5s 900s docker run "${common[@]}" --network bridge \
    -v "$dependency_directory/inputs:/dependencies:ro" -v "$mirror_directory:/providers:rw" \
    -w /source "$image" python3 -I -B /source/scripts/workflow_terraform.py fetch \
    --directory /dependencies --mirror /providers
  terraform_mounts=(-v "$dependency_directory/inputs/terraformrc:/terraformrc:ro"
    -v "$mirror_directory:/providers:ro" -e TF_CLI_CONFIG_FILE=/terraformrc)
fi
# Source-owned validation: offline, no token, no service socket, read-only inputs.
timeout -k 5s 1500s docker run "${common[@]}" --network none \
  "${terraform_mounts[@]}" \
  -v "$candidate_root:/workspace:ro" -v "$policy_directory/policy.json:/policy.json:ro" \
  -w /workspace "$image" \
  python3 -I -B /source/scripts/workflow_common_quality.py validate --policy /policy.json
