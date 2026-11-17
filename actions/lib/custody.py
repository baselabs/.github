"""The qualified OCI record: input validation, descriptors, and byte verification.

Network operations belong to the bash entrypoints using gh and ORAS. This module
uses only Python's standard library and never handles an authentication token.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys

ARTIFACT_TYPE = 'application/vnd.baselabs.qualified.v1'
MANIFEST_TYPE = 'application/vnd.oci.image.manifest.v1+json'
LAYER_TYPE = 'application/octet-stream'
TITLE = 'org.opencontainers.image.title'
SHA = re.compile(r'[0-9a-f]{40}\Z')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')
IMAGE = re.compile(r'ghcr\.io/[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+@sha256:[0-9a-f]{64}\Z')
IMAGE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*\Z')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, separators=(',', ':')), encoding='utf-8')


def file_digest(path):
    with Path(path).open('rb') as file:
        digest = hashlib.sha256()
        for block in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(block)
    return 'sha256:' + digest.hexdigest()


def positive(value, label):
    require(isinstance(value, (str, int)) and not isinstance(value, bool)
            and re.fullmatch(r'[1-9][0-9]*', str(value)), label + ' must be a positive integer')
    return int(value)


def identity(env):
    sha, repository = env['CUSTODY_SHA'], env['CUSTODY_REPOSITORY']
    require(SHA.fullmatch(sha), 'sha must be a full 40-character lowercase commit SHA')
    parts = repository.split('/')
    require(len(parts) == 2 and parts[0].lower() == 'baselabs'
            and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', parts[1])
            and parts[1] not in ('.', '..'), 'repository must belong to baselabs')
    name = 'dot-github' if parts[1].lower() == '.github' else parts[1].lower()
    return sha, repository, 'ghcr.io/baselabs/' + name + '/qualified'


def safe_title(name):
    require(isinstance(name, str) and name and name not in ('.', '..')
            and '/' not in name and '\\' not in name
            and not any(ord(c) < 32 or ord(c) == 127 for c in name),
            'layer title must be a safe, nonempty basename')
    return name


def image_object(value):
    require(isinstance(value, dict) and value, 'images.json must be a nonempty JSON object')
    for name, reference in value.items():
        require(IMAGE_NAME.fullmatch(name) and isinstance(reference, str)
                and IMAGE.fullmatch(reference), 'images must be named GHCR sha256 digest references')
    return value


def parse_images(value):
    images = {}
    for line in value.splitlines():
        if not line:
            continue
        name, separator, reference = line.partition('=')
        require(separator and name not in images, 'invalid or duplicate image name')
        images[name] = reference
    return image_object(images) if value else {}


def descriptor(path, media_type, name=None):
    result = {'mediaType': media_type, 'digest': file_digest(path), 'size': path.stat().st_size}
    if name is not None:
        result['annotations'] = {TITLE: name}
    return result


def prepare_store(work, env):
    sha, repository, _ = identity(env)
    require(env['CUSTODY_EVENT_NAME'] == 'push' and env['CUSTODY_REF'] == 'refs/heads/kci/' + sha,
            'qualified-store only accepts a push to refs/heads/kci/<github.sha>')
    run_id = positive(env['CUSTODY_RUN_ID'], 'run-id')
    attempt = positive(env['CUSTODY_RUN_ATTEMPT'], 'run-attempt')
    require(env['CUSTODY_WORKFLOW_REF'], 'workflow-ref is required')
    images = parse_images(env.get('CUSTODY_IMAGES', ''))
    files, names = [], set()
    for entry in env.get('CUSTODY_FILES', '').splitlines():
        if not entry:
            continue
        path = Path(entry)
        require(stat.S_ISREG(path.lstat().st_mode), 'every files input must be a regular file')
        name = safe_title(path.name)
        require(name not in names, 'files input contains duplicate basenames')
        require(name != 'images.json', 'images.json is reserved for the images input')
        names.add(name)
        files.append((path, name))
    require(files or images, 'supply at least one regular file or image')
    payloads = work / 'payloads'
    payloads.mkdir()
    layers, originals = [], []
    for i, (path, name) in enumerate(files):
        target = payloads / str(i)
        shutil.copyfile(path, target)
        layers.append(descriptor(target, LAYER_TYPE, name))
        originals.append(str(path.absolute()))
    if images:
        target = payloads / str(len(layers))
        write_json(target, images)
        layers.append(descriptor(target, LAYER_TYPE, 'images.json'))
        originals.append(None)
    config = work / 'config.json'
    config.write_bytes(b'{}')
    manifest = {
        'schemaVersion': 2,
        'mediaType': MANIFEST_TYPE,
        'artifactType': ARTIFACT_TYPE,
        'config': descriptor(config, 'application/vnd.oci.empty.v1+json'),
        'layers': layers,
        'annotations': {
            'org.opencontainers.image.revision': sha,
            'org.opencontainers.image.source': 'https://github.com/' + repository,
            'org.baselabs.run-id': str(run_id),
            'org.baselabs.run-attempt': str(attempt),
            'org.baselabs.workflow-ref': env['CUSTODY_WORKFLOW_REF'],
        },
    }
    write_json(work / 'manifest.json', manifest)
    write_json(work / 'originals.json', originals)
    (work / 'payloads.list').write_text(''.join(str(i) + '\n' for i in range(len(layers))))


def manifest_at(path, digest):
    require(DIGEST.fullmatch(digest) and file_digest(path) == digest, 'manifest digest mismatch')
    manifest = read_json(path)
    require(manifest.get('schemaVersion') == 2 and manifest.get('mediaType') == MANIFEST_TYPE
            and manifest.get('artifactType') == ARTIFACT_TYPE, 'not a qualified v1 OCI manifest')
    layers = manifest.get('layers')
    require(isinstance(layers, list) and layers, 'record has no payload layers')
    names = set()
    for layer in layers:
        require(isinstance(layer, dict), 'invalid layer descriptor')
        name = safe_title(layer.get('annotations', {}).get(TITLE))
        require(name not in names, 'record has duplicate layer titles')
        names.add(name)
        require(layer.get('mediaType') == LAYER_TYPE and isinstance(layer.get('digest'), str)
                and DIGEST.fullmatch(layer['digest']) and type(layer.get('size')) is int
                and layer['size'] >= 0, 'invalid layer media type, digest, or size')
    return manifest


def verify_file(path, layer):
    require(path.is_file() and not path.is_symlink() and file_digest(path) == layer['digest']
            and path.stat().st_size == layer['size'], 'payload digest or size mismatch')


def verify_store(work, digest):
    actual = manifest_at(work / 'returned.json', digest)
    require(actual == read_json(work / 'manifest.json'), 'returned manifest differs from the stored record')
    originals = read_json(work / 'originals.json')
    for i, layer in enumerate(actual['layers']):
        verify_file(work / 'payloads' / str(i), layer)
        if originals[i] is not None:
            verify_file(Path(originals[i]), layer)


def qualified_check(pages, sha):
    checks = [check for page in pages for check in page['check_runs']]
    require(len(checks) == 1 and all(page['total_count'] == 1 for page in pages),
            'commit must have exactly one latest qualified check')
    check = checks[0]
    require(check.get('name') == 'qualified' and check.get('app', {}).get('slug') == 'github-actions'
            and check.get('head_sha') == sha and check.get('status') == 'completed'
            and check.get('conclusion') == 'success', 'qualified must be successful and from github-actions')
    return positive(check['id'], 'qualified check id')


def qualified_job(job, check_id, sha):
    require(job.get('id') == int(check_id) and job.get('head_sha') == sha
            and job.get('status') == 'completed' and job.get('conclusion') == 'success',
            'Actions job does not match the successful qualified check')
    return positive(job.get('run_id'), 'qualified run id'), positive(job.get('run_attempt'), 'qualified run attempt')


def prepare_fetch(work, digest, env):
    sha, repository, _ = identity(env)
    manifest = manifest_at(work / 'manifest.json', digest)
    job = read_json(work / 'job.json')
    run_id, attempt = qualified_job(job, job['id'], sha)
    annotations = manifest.get('annotations', {})
    require(annotations.get('org.opencontainers.image.revision') == sha
            and annotations.get('org.opencontainers.image.source') == 'https://github.com/' + repository,
            'record revision or source does not match this commit and repository')
    require(annotations.get('org.baselabs.run-id') == str(run_id), 'record belongs to another workflow run')
    stored_attempt = positive(annotations.get('org.baselabs.run-attempt'), 'record run attempt')
    require(stored_attempt <= attempt, 'record is from a later attempt than qualified')
    require(isinstance(annotations.get('org.baselabs.workflow-ref'), str)
            and annotations['org.baselabs.workflow-ref'], 'record is missing workflow-ref')
    directory = env['CUSTODY_DIRECTORY']
    require(directory and not any(ord(c) < 32 or ord(c) == 127 for c in directory), 'directory is required and must not contain control characters')
    (work / 'payloads').mkdir()
    (work / 'payloads.list').write_text(''.join(str(i) + '\n' for i in range(len(manifest['layers']))))


def finish_fetch(work, digest, env):
    manifest = manifest_at(work / 'manifest.json', digest)
    directory = Path(env['CUSTODY_DIRECTORY']).absolute()
    require(not directory.is_symlink(), 'destination directory must not be a symlink')
    directory.mkdir(parents=True, exist_ok=True)
    images = ''
    # Verify all bytes and destination entries before making any payload available.
    for i, layer in enumerate(manifest['layers']):
        path = work / 'payloads' / str(i)
        verify_file(path, layer)
        name = layer['annotations'][TITLE]
        target = directory / name
        require(not target.is_symlink() and (not target.exists() or target.is_file()), 'destination payload must not be a symlink or directory')
        if name == 'images.json':
            image_object(read_json(path))
            images = str(target)
    for i, layer in enumerate(manifest['layers']):
        shutil.copyfile(work / 'payloads' / str(i), directory / layer['annotations'][TITLE])
        verify_file(directory / layer['annotations'][TITLE], layer)
    with Path(env['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
        output.write('digest=' + digest + '\ndirectory=' + str(directory) + '\nimages=' + images + '\n')
    with Path(env['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as summary:
        summary.write('Fetched qualified payloads: `' + identity(env)[2] + '@' + digest + '`.\n')


def main():
    command, *args = sys.argv[1:]
    env = os.environ
    if command == 'registry':
        print(identity(env)[2])
    elif command == 'prepare-store':
        prepare_store(Path(args[0]), env)
    elif command == 'verify-store':
        verify_store(Path(args[0]), args[1])
    elif command == 'qualified-check':
        print(qualified_check(read_json(args[0]), env['CUSTODY_SHA']))
    elif command == 'qualified-job':
        qualified_job(read_json(args[0]), args[1], env['CUSTODY_SHA'])
    elif command == 'prepare-fetch':
        prepare_fetch(Path(args[0]), args[1], env)
    elif command == 'finish-fetch':
        finish_fetch(Path(args[0]), args[1], env)
    else:
        raise ValueError('unknown custody operation')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, TypeError) as error:
        sys.exit('Qualified custody refused: ' + str(error))
