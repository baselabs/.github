#!/usr/bin/env bash
set -euo pipefail
umask 077
lib="${BASH_SOURCE[0]%/*}/../lib"
# shellcheck source=../lib/oras.sh
source "$lib/oras.sh"
work="$(mktemp -d "$RUNNER_TEMP/qualified-store.XXXXXXXX")"
trap 'rm -rf -- "$work"' EXIT

# Validate the event and every input before downloading tools or authenticating.
python3 -B "$lib/custody.py" prepare-store "$work"
registry="$(python3 -B "$lib/custody.py" registry)"
custody_oras
auth="$work/auth.json"
custody_login "$auth"

oras blob push --registry-config "$auth" "$registry" "$work/config.json" >/dev/null
while IFS= read -r file; do
  oras blob push --registry-config "$auth" "$registry" "$work/payloads/$file" >/dev/null
done < "$work/payloads.list"
oras manifest push --registry-config "$auth" --descriptor \
  "$registry:$CUSTODY_SHA" "$work/manifest.json" > "$work/descriptor.json"
digest="$(jq -er '.digest | select(test("^sha256:[0-9a-f]{64}$"))' "$work/descriptor.json")"
oras manifest fetch --registry-config "$auth" "$registry@$digest" --output "$work/returned.json"
python3 -B "$lib/custody.py" verify-store "$work" "$digest"
printf 'digest=%s\n' "$digest" >> "$GITHUB_OUTPUT"
printf 'Stored qualified payloads: %s@%s (run %s, attempt %s).\n' \
  "$registry" "$digest" "$CUSTODY_RUN_ID" "$CUSTODY_RUN_ATTEMPT" >> "$GITHUB_STEP_SUMMARY"
