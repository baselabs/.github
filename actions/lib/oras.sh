#!/usr/bin/env bash
set -euo pipefail

# Shared with the estate's runner declaration in infra's bin/lib/infra_tools.sh.
CUSTODY_ORAS_VERSION=1.3.0
CUSTODY_ORAS_SHA256=6cdc692f929100feb08aa8de584d02f7bcc30ec7d88bc2adc2054d782db57c64

custody_oras() {
  case "$CUSTODY_RUNNER_ENVIRONMENT" in
    github-hosted)
      if [[ "$RUNNER_OS/$RUNNER_ARCH" != Linux/X64 ]]; then
        echo 'qualified custody requires a Linux X64 GitHub-hosted runner' >&2
        return 1
      fi
      local install_dir archive
      install_dir="$(mktemp -d "$RUNNER_TEMP/qualified-oras.XXXXXXXX")"
      archive="oras_${CUSTODY_ORAS_VERSION}_linux_amd64.tar.gz"
      gh release download "v$CUSTODY_ORAS_VERSION" --repo oras-project/oras \
        --pattern "$archive" --dir "$install_dir"
      python3 - "$install_dir" "$archive" "$CUSTODY_ORAS_SHA256" <<'PY'
import hashlib
from pathlib import Path
import sys
import tarfile

directory, name, expected = sys.argv[1:]
archive = Path(directory) / name
try:
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise SystemExit('ORAS release checksum mismatch')
    with tarfile.open(archive, 'r:gz') as tar:
        member = tar.getmember('oras')
        if not member.isfile():
            raise SystemExit('ORAS release binary is not a regular file')
        binary = Path(directory) / 'oras'
        binary.write_bytes(tar.extractfile(member).read())
        binary.chmod(0o755)
finally:
    archive.unlink(missing_ok=True)
PY
      export PATH="$install_dir:$PATH"
      printf '%s\n' "$install_dir" >> "$GITHUB_PATH"
      ;;
    self-hosted)
      command -v oras >/dev/null || {
        echo 'self-hosted runners must provide the declared ORAS version on PATH' >&2
        return 1
      }
      ;;
    *)
      echo 'unknown runner environment; expected github-hosted or self-hosted' >&2
      return 1
      ;;
  esac
  local actual
  actual="$(oras version | python3 -c 'import sys; print(next((s.split(":", 1)[1].strip() for s in sys.stdin if s.startswith("Version:")), ""))')"
  if [[ "$actual" != "$CUSTODY_ORAS_VERSION" ]]; then
    echo "ORAS $CUSTODY_ORAS_VERSION is required; found $actual" >&2
    return 1
  fi
}

custody_login() {
  printf '%s' "$GH_TOKEN" | oras login ghcr.io \
    --username "$CUSTODY_ACTOR" --password-stdin --registry-config "$1" >/dev/null
}
