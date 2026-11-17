# Qualified artifact custody

Every BaseLabs repository that publishes bytes builds them once in its candidate
workflow on `kci/<full commit SHA>`. Before `qualified` succeeds, store the tested
payloads in GHCR. Default-branch, tag, and release jobs fetch those bytes for
publication. A missing record or digest mismatch fails publication.

These actions are public and work from public and private repositories. Pin both
to the implementation commit:

```yaml
uses: baselabs/.github/actions/qualified-store@ecf340e8907d6aac1e6fb6808353b6c616236208 # qualified custody v1
uses: baselabs/.github/actions/qualified-fetch@ecf340e8907d6aac1e6fb6808353b6c616236208 # qualified custody v1
```

## Store a candidate

The candidate job needs `contents: read` and `packages: write`. It must be a
`push` event on exactly `refs/heads/kci/${{ github.sha }}`. Call store once after
the repository's build and proofs have passed against the payloads:

```yaml
- name: Store tested payloads
  id: custody
  uses: baselabs/.github/actions/qualified-store@ecf340e8907d6aac1e6fb6808353b6c616236208 # qualified custody v1
  with:
    files: |
      dist/package.tar
      dist/artifact.tar
    images: |
      app=${{ steps.image.outputs.ref }}
```

`files` and `images` are newline-separated. Supply either or both; at least one
payload is required. Files must exist and be regular files, with unique basenames
(symlinks and directories are refused). Fetch flattens their paths to those
basenames. `images.json` is reserved for the generated image map. Image references
have the form `name=ghcr.io/owner/image@sha256:<64 lowercase hex characters>`;
names must be unique and use letters, digits, dots, underscores, or hyphens,
starting with a letter or digit. Push and test the referenced image before store.

The output `digest` identifies the OCI manifest. The action also writes the
registry identity, run id, and attempt to the step summary. Each repository has
one record per candidate SHA at:

```text
ghcr.io/baselabs/<lowercase repository name>/qualified:<full commit SHA>
```

The `.github` repository uses `dot-github` as its package-name component. The
manifest's artifact type is `application/vnd.baselabs.qualified.v1`. Each file is
an `application/octet-stream` layer with its basename as
`org.opencontainers.image.title`. Images add an `images.json` layer containing a
JSON object from image name to digest reference. The manifest records:

- `org.opencontainers.image.revision`
- `org.opencontainers.image.source` (`https://github.com/<owner>/<repository>`)
- `org.baselabs.run-id`
- `org.baselabs.run-attempt`
- `org.baselabs.workflow-ref`

The action reads the manifest back by digest and checks every layer against the
local bytes before succeeding. Keep the registry records and referenced image
digests for as long as their commits may be published. An expiring Actions
artifact is never their only copy. One store invocation owns the commit's tag;
combine payloads from multiple build jobs before storing, rather than letting
several jobs overwrite the record.

## Fetch for publication

The publication job needs `contents: read`, `packages: read`, `checks: read`, and
`actions: read`. It must run only after promotion, on the default branch, a tag,
or a release. Publication credentials belong to this job alone.

```yaml
- name: Fetch the qualified bytes
  id: custody
  uses: baselabs/.github/actions/qualified-fetch@ecf340e8907d6aac1e6fb6808353b6c616236208 # qualified custody v1
  with:
    directory: ${{ runner.temp }}/qualified
    # sha defaults to github.sha; specify a full commit SHA when publishing another commit.
```

Outputs are `digest` (manifest digest), `directory` (absolute destination), and
`images` (absolute path to `images.json`, or empty when absent). The destination
may contain regular files, which are replaced only after all fetched payloads
have passed verification; destination symlinks or directories in place of files
are refused. Do not run consumers concurrently in the same destination.

Fetch requires exactly one latest `qualified` check from the `github-actions`
app, completed successfully. It reads that check's Actions job to obtain the run
id and attempt. The record must match this repository, revision, and run id, and
its attempt must be no later than the qualified job's attempt. This permits
rerunning failed jobs while retaining an earlier successful store. A rerun of
the storing job replaces the SHA tag with its new attempt. Fetch resolves the
tag once, reads the manifest and each layer by digest, and verifies all bytes
before exposing outputs. It never falls back to a rebuild or an Actions upload.

## Runner tools and credentials

Both actions use bash, `gh`, `jq`, Python 3's standard library, and ORAS. On a
GitHub-hosted Linux X64 runner they download ORAS 1.3.0 into `RUNNER_TEMP`, verify
the release SHA256, and put its directory on the job's PATH. On a self-hosted
runner they require exactly ORAS 1.3.0 on PATH and refuse a missing or different
version. There is no download fallback for self-hosted runners. The version and
checksum live once in [lib/oras.sh](lib/oras.sh), matching the estate's infra
declaration.

Registry login uses `github.token` through stdin. Each invocation keeps its auth
file in a private temporary directory and removes it on exit, leaving any
existing Docker/ORAS credentials untouched. A later publication command needing
registry access must authenticate with the publication job's own token. A
private GHCR package must grant this repository's Actions token access; making
this action repository public does not make a consumer's payload package public.

## GitHub Pages

Build and check the site in the candidate job, then create `artifact.tar` once
with the same archive options as
[`actions/upload-pages-artifact`](https://github.com/actions/upload-pages-artifact/blob/main/action.yml).
For the default hidden-file policy on Linux:

```bash
set -euo pipefail
tar --dereference --hard-dereference --directory _site \
  -cvf "$RUNNER_TEMP/artifact.tar" \
  --exclude=.git --exclude=.github --exclude='.[^/]*' .
```

Store `$RUNNER_TEMP/artifact.tar` with `qualified-store`. If the site includes
hidden assets, choose that policy in the candidate and omit only the hidden-file
exclusion there. Publication does not make a second archive.

The default-branch publication job fetches custody, uploads that exact tar as
the `github-pages` Actions artifact, then deploys it. Declare `pages: write` and
`id-token: write` in addition to fetch's read permissions, and use the
repository's `github-pages` environment:

```yaml
- name: Fetch the tested Pages archive
  id: custody
  uses: baselabs/.github/actions/qualified-fetch@ecf340e8907d6aac1e6fb6808353b6c616236208 # qualified custody v1
  with:
    directory: ${{ runner.temp }}/qualified-pages
- name: Upload the stored archive unchanged
  uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
  with:
    name: github-pages
    path: ${{ steps.custody.outputs.directory }}/artifact.tar
    compression-level: 0
    if-no-files-found: error
- name: Deploy Pages
  id: deployment
  uses: actions/deploy-pages@368f82528645a54fb793d4d04e342629a3f51346 # v5.0.1
```

Keep the product's published-site availability checks after deployment.

## Hex

The candidate runs `mix hex.build` and stores its resulting `name-version.tar`.
Publication must not run `mix hex.publish`: Hex 2.7.0 accepts only the current
project (`package`, `docs`, or both), with no prebuilt tarball argument, and
[`create_release/5` constructs a new tarball](https://github.com/hexpm/hex/blob/d12d58dd413deb5a9f8cb0fbb4eb1244e7074a42/lib/mix/tasks/hex.publish.ex#L514).
See also the [task documentation](https://hex.hexdocs.pm/Mix.Tasks.Hex.Publish.html).

Send the stored tarball directly to the Hex HTTP API:
`POST https://hex.pm/api/packages/<name>/releases?replace=false`, using
`Content-Type: application/octet-stream` and the API key in the `Authorization`
header. Private repositories prefix the path with `/repos/<organization>`.
This is the endpoint used by
[`hex_api_release:publish`](https://github.com/hexpm/hex_core/blob/2de9dc33d00a39804f9ac1e2df3054edc986cc50/src/hex_api_release.erl#L114).

After fetch, run this in the publication job, with `HEX_TARBALL` set to the
fetched file's absolute path, `HEX_PACKAGE` and `HEX_VERSION` set to the release
identity, optional `HEX_ORGANIZATION` for a private repository, and `HEX_API_KEY`
provided only to this step through its secret environment:

```yaml
- name: Publish the stored Hex tarball and read back its checksum
  env:
    HEX_TARBALL: ${{ steps.custody.outputs.directory }}/my_package-1.2.3.tar
    HEX_PACKAGE: my_package
    HEX_VERSION: 1.2.3
    HEX_API_KEY: ${{ secrets.HEX_API_KEY }}
  shell: bash
  run: |
    set -euo pipefail
    python3 - <<'PY'
    import hashlib, json, os
    from pathlib import Path
    from urllib.parse import quote
    from urllib.request import Request, urlopen

    tarball = Path(os.environ['HEX_TARBALL']).read_bytes()
    expected = hashlib.sha256(tarball).hexdigest()
    base = 'https://hex.pm/api'
    organization = os.environ.get('HEX_ORGANIZATION', '')
    if organization:
        base += '/repos/' + quote(organization, safe='')
    releases = base + '/packages/' + quote(os.environ['HEX_PACKAGE'], safe='') + '/releases'
    headers = {'Authorization': os.environ['HEX_API_KEY'], 'Accept': 'application/json'}
    request = Request(releases + '?replace=false', data=tarball, method='POST',
                      headers={**headers, 'Content-Type': 'application/octet-stream'})
    with urlopen(request, timeout=120) as response:
        result = json.load(response)
    if result.get('status') == 'staged':
        raise SystemExit('Release is staged: obtain approval and poll its status before declaring publication successful')
    release = releases + '/' + quote(os.environ['HEX_VERSION'], safe='')
    with urlopen(Request(release, headers=headers), timeout=30) as response:
        published = json.load(response)
    if published.get('checksum') != expected:
        raise SystemExit('Published Hex checksum differs from the qualified tarball')
    print('Published Hex checksum matches the qualified tarball.')
    PY
```

The release API's `checksum` is SHA256 of the complete tarball (the outer
checksum), not the inner `CHECKSUM` member. The
[`HexpmWeb.API.ReleaseView` implementation](https://github.com/hexpm/hexpm/blob/92147c5982cfdf4fe34f742efbf9ae5ecf069beb/lib/hexpm_web/views/api/release_view.ex#L14)
confirms that mapping. For staged publishing, the product must complete its
configured approval/polling flow and the same read-back check; a staged response
alone is not publication. If publishing docs too, build and store their archive
in the candidate and send that archive to the docs endpoint, without `mix docs`
in publication.

## npm

The candidate uses `npm pack` once, after building and testing the package, and
stores that `.tgz`. After fetch, the publication job uses its pinned Node/npm
toolchain and configured registry authentication to publish the tarball:

```bash
set -euo pipefail
npm publish --ignore-scripts "$NPM_TARBALL"
expected="$(python3 - "$NPM_TARBALL" <<'PY'
import base64, hashlib, sys
from pathlib import Path
print('sha512-' + base64.b64encode(hashlib.sha512(Path(sys.argv[1]).read_bytes()).digest()).decode())
PY
)"
actual="$(npm view "$NPM_PACKAGE@$NPM_VERSION" dist.integrity)"
test "$actual" = "$expected"
```

`NPM_TARBALL` is the fetched absolute path. Set `NPM_PACKAGE`, `NPM_VERSION`, and
the publication job's registry credential through the environment. The
[`npm publish` tarball input](https://docs.npmjs.com/cli/v11/commands/npm-publish/)
sends the stored package; `--ignore-scripts` prevents publication lifecycle hooks
from rebuilding it. Keep the consumer-install and availability checks after
publication, using the registry version whose integrity was read back.

## Container images

The candidate pushes its built and tested image to GHCR by digest and supplies
that digest as an `images` entry. Image-only candidates can omit `files`.
Publication fetches the record, reads the named reference from `images.json`,
and promotes the same manifest. The publication job needs `packages: write` in
addition to `checks: read` and `actions: read`.

With `IMAGES` set to fetch's `images` output, `RELEASE_TAG` to the target tag, and
`GH_TOKEN` supplied through the publication step's secret environment:

```bash
set -euo pipefail
ref="$(jq -er '.app' "$IMAGES")"
expected="${ref##*@}"
repository="${ref%@*}"
auth_dir="$(mktemp -d "$RUNNER_TEMP/publish-auth.XXXXXXXX")"
trap 'rm -rf -- "$auth_dir"' EXIT
printf '%s' "$GH_TOKEN" | oras login ghcr.io --username "$GITHUB_ACTOR" \
  --password-stdin --registry-config "$auth_dir/config.json"
oras tag --registry-config "$auth_dir/config.json" "$ref" "$RELEASE_TAG"
actual="$(oras manifest fetch --registry-config "$auth_dir/config.json" \
  --descriptor "$repository:$RELEASE_TAG" | jq -er '.digest')"
test "$actual" = "$expected"
```

`oras tag` preserves the referenced manifest's bytes. An existing Docker-based
publisher can instead use
`docker buildx imagetools create --prefer-index=false --tag "$repository:$RELEASE_TAG" "$ref"`
and read the digest back with `docker buildx imagetools inspect`. The
[`--prefer-index=false` option](https://docs.docker.com/reference/cli/docker/buildx/imagetools/create/)
prevents the default wrapping of a single-platform manifest in a new index;
always require the resulting digest to equal the stored digest. Do not rebuild,
append platforms, or add annotations during promotion. Keep deployment and
availability checks against the promoted digest.

## This repository's proof

[ci.yml](../.github/workflows/ci.yml) runs only on candidate pushes, on
GitHub-hosted Ubuntu 24.04. It lints workflows and action scripts, exercises
record/input rejection and byte validation, and stores two deterministic files
in the real GHCR package. `qualified` always runs and accepts only successful
results from every prerequisite. [verify-custody.yml](../.github/workflows/verify-custody.yml)
runs only on `main`, fetches the live record bound to that commit's successful
check, and compares every byte with the deterministic payload definition. No
build or test uses the operator's Mac or the estate's build box.
