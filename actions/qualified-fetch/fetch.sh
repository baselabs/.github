#!/usr/bin/env bash
set -euo pipefail
umask 077
lib="${BASH_SOURCE[0]%/*}/../lib"
# shellcheck source=../lib/oras.sh
source "$lib/oras.sh"
work="$(mktemp -d "$RUNNER_TEMP/qualified-fetch.XXXXXXXX")"
trap 'rm -rf -- "$work"' EXIT

registry="$(python3 -B "$lib/custody.py" registry)"
gh api --paginate --slurp \
  "repos/$CUSTODY_REPOSITORY/commits/$CUSTODY_SHA/check-runs?check_name=qualified&filter=latest&per_page=100" \
  > "$work/checks.json"
check_id="$(python3 -B "$lib/custody.py" qualified-check "$work/checks.json")"
gh api "repos/$CUSTODY_REPOSITORY/actions/jobs/$check_id" > "$work/job.json"
python3 -B "$lib/custody.py" qualified-job "$work/job.json" "$check_id"

custody_oras
auth="$work/auth.json"
custody_login "$auth"
oras manifest fetch --registry-config "$auth" --descriptor \
  "$registry:$CUSTODY_SHA" > "$work/descriptor.json"
digest="$(jq -er '.digest | select(test("^sha256:[0-9a-f]{64}$"))' "$work/descriptor.json")"
# Resolve once, then read by digest, so a concurrent tag update cannot change the bytes.
oras manifest fetch --registry-config "$auth" "$registry@$digest" --output "$work/manifest.json"
python3 -B "$lib/custody.py" prepare-fetch "$work" "$digest"
while IFS= read -r layer; do
  layer_digest="$(jq -er --argjson i "$layer" '.layers[$i].digest' "$work/manifest.json")"
  oras blob fetch --registry-config "$auth" "$registry@$layer_digest" --output "$work/payloads/$layer"
done < "$work/payloads.list"
python3 -B "$lib/custody.py" finish-fetch "$work" "$digest"
