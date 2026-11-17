"""Pure record/byte validation; service behavior is proven by the live CI round trip."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('custody', Path(__file__).resolve().parents[1] / 'actions/lib/custody.py')
custody = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(custody)
SHA = 'a' * 40
IMAGE = 'ghcr.io/baselabs/example@sha256:' + 'b' * 64


class CustodyTests(unittest.TestCase):
    def setUp(self):
        self.scope = tempfile.TemporaryDirectory()
        self.addCleanup(self.scope.cleanup)
        self.root = Path(self.scope.name)
        self.work = self.root / 'store'
        self.work.mkdir()
        self.file = self.root / 'payload with spaces.bin'
        self.file.write_bytes(bytes(range(256)))
        self.env = {
            'CUSTODY_SHA': SHA, 'CUSTODY_REPOSITORY': 'baselabs/.github',
            'CUSTODY_EVENT_NAME': 'push', 'CUSTODY_REF': 'refs/heads/kci/' + SHA,
            'CUSTODY_RUN_ID': '123', 'CUSTODY_RUN_ATTEMPT': '2',
            'CUSTODY_WORKFLOW_REF': 'baselabs/.github/.github/workflows/ci.yml@refs/heads/kci/' + SHA,
            'CUSTODY_FILES': str(self.file), 'CUSTODY_IMAGES': '',
            'CUSTODY_DIRECTORY': str(self.root / 'destination'),
            'GITHUB_OUTPUT': str(self.root / 'output'),
            'GITHUB_STEP_SUMMARY': str(self.root / 'summary'),
        }
        self.job = {'id': 456, 'run_id': 123, 'run_attempt': 2, 'head_sha': SHA,
                    'status': 'completed', 'conclusion': 'success'}

    def store(self):
        custody.prepare_store(self.work, self.env)
        manifest = self.work / 'manifest.json'
        shutil.copyfile(manifest, self.work / 'returned.json')
        digest = custody.file_digest(manifest)
        custody.verify_store(self.work, digest)
        return digest

    def fetch(self, digest):
        target = self.root / 'fetch'
        target.mkdir()
        shutil.copyfile(self.work / 'manifest.json', target / 'manifest.json')
        custody.write_json(target / 'job.json', self.job)
        custody.prepare_fetch(target, digest, self.env)
        for path in (self.work / 'payloads').iterdir():
            shutil.copyfile(path, target / 'payloads' / path.name)
        return target

    def test_registry_identity_and_full_sha(self):
        self.assertEqual(custody.identity(self.env)[2], 'ghcr.io/baselabs/dot-github/qualified')
        self.env['CUSTODY_REPOSITORY'] = 'BaseLabs/Some_Repo'
        self.assertEqual(custody.identity(self.env)[2], 'ghcr.io/baselabs/some_repo/qualified')
        for value in ['short', 'a' * 39, 'A' * 40, '../' + SHA]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                custody.identity(dict(self.env, CUSTODY_SHA=value))

    def test_store_rejects_non_candidate_events(self):
        for event, ref in [('pull_request', self.env['CUSTODY_REF']), ('push', 'refs/heads/main'),
                           ('push', 'refs/heads/kci/' + 'b' * 40), ('workflow_dispatch', self.env['CUSTODY_REF'])]:
            with self.subTest(event=event, ref=ref), self.assertRaises(ValueError):
                custody.prepare_store(self.work, dict(self.env, CUSTODY_EVENT_NAME=event, CUSTODY_REF=ref))

    def test_store_rejects_missing_directory_symlink_and_duplicate_basenames(self):
        other = self.root / 'other'
        other.mkdir()
        duplicate = other / self.file.name
        duplicate.write_bytes(b'other')
        link = self.root / 'link'
        link.symlink_to(self.file)
        for value in [str(self.root / 'missing'), str(other), str(link), str(self.file) + '\n' + str(duplicate)]:
            with self.subTest(value=value), self.assertRaises((ValueError, OSError)):
                custody.prepare_store(self.work, dict(self.env, CUSTODY_FILES=value))

    def test_images_only_and_image_validation(self):
        self.env.update(CUSTODY_FILES='', CUSTODY_IMAGES='app=' + IMAGE)
        digest = self.store()
        target = self.fetch(digest)
        custody.finish_fetch(target, digest, self.env)
        images = self.root / 'destination/images.json'
        self.assertEqual(custody.read_json(images), {'app': IMAGE})
        self.assertIn('images=' + str(images), (self.root / 'output').read_text())
        for value in ['app=image:latest', 'app=' + IMAGE + '\napp=' + IMAGE, '=x', 'app=ghcr.io/a/b@sha256:short', '\n']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                custody.parse_images(value)

    def test_original_file_mutation_is_detected_after_store(self):
        digest = self.store()
        self.file.write_bytes(b'changed during the push')
        with self.assertRaisesRegex(ValueError, 'payload digest'):
            custody.verify_store(self.work, digest)

    def test_check_requires_exactly_one_successful_actions_check(self):
        check = dict(self.job, name='qualified', app={'slug': 'github-actions'})
        valid = [{'total_count': 1, 'check_runs': [check]}]
        self.assertEqual(custody.qualified_check(valid, SHA), 456)
        invalid = [[], [{'total_count': 0, 'check_runs': []}],
                   [{'total_count': 2, 'check_runs': [check, check]}]]
        for update in [{'conclusion': 'failure'}, {'conclusion': 'skipped'}, {'status': 'in_progress'},
                       {'app': {'slug': 'other'}}, {'head_sha': 'b' * 40}, {'name': 'other'}]:
            invalid.append([{'total_count': 1, 'check_runs': [dict(check, **update)]}])
        for pages in invalid:
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                custody.qualified_check(pages, SHA)
        with self.assertRaises(ValueError):
            custody.qualified_job(dict(self.job, id=999), 456, SHA)

    def test_record_provenance_and_rerun_attempts(self):
        self.store()
        original = custody.read_json(self.work / 'manifest.json')
        for key, value in [('org.opencontainers.image.revision', 'b' * 40),
                           ('org.opencontainers.image.source', 'https://github.com/baselabs/other'),
                           ('org.baselabs.run-id', '999'), ('org.baselabs.run-attempt', '3'),
                           ('org.baselabs.run-attempt', '0'), ('org.baselabs.workflow-ref', '')]:
            with self.subTest(key=key, value=value):
                manifest = copy.deepcopy(original)
                manifest['annotations'][key] = value
                custody.write_json(self.work / 'manifest.json', manifest)
                with self.assertRaises(ValueError):
                    self.fetch(custody.file_digest(self.work / 'manifest.json'))
                shutil.rmtree(self.root / 'fetch')
        custody.write_json(self.work / 'manifest.json', original)
        self.job['run_attempt'] = 3
        self.fetch(custody.file_digest(self.work / 'manifest.json'))

    def test_manifest_and_payload_tampering_fail_before_delivery(self):
        digest = self.store()
        with self.assertRaisesRegex(ValueError, 'manifest digest'):
            custody.manifest_at(self.work / 'manifest.json', 'sha256:' + '0' * 64)
        target = self.fetch(digest)
        (target / 'payloads/0').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'payload digest'):
            custody.finish_fetch(target, digest, self.env)
        self.assertFalse((self.root / 'destination' / self.file.name).exists())
        self.assertFalse((self.root / 'output').exists())

    def test_titles_cannot_escape_destination_or_collide(self):
        self.store()
        original = custody.read_json(self.work / 'manifest.json')
        for name in ['../escape', '/absolute', '.', '..', 'nested/file', 'nested\\file', 'bad\nname']:
            with self.subTest(name=name):
                manifest = copy.deepcopy(original)
                manifest['layers'][0]['annotations'][custody.TITLE] = name
                custody.write_json(self.work / 'manifest.json', manifest)
                with self.assertRaises(ValueError):
                    custody.manifest_at(self.work / 'manifest.json', custody.file_digest(self.work / 'manifest.json'))
        original['layers'].append(copy.deepcopy(original['layers'][0]))
        custody.write_json(self.work / 'manifest.json', original)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            custody.manifest_at(self.work / 'manifest.json', custody.file_digest(self.work / 'manifest.json'))

    def test_symlink_destination_refused_and_normal_binary_round_trip(self):
        digest = self.store()
        target = self.fetch(digest)
        destination = self.root / 'destination'
        destination.mkdir()
        victim = self.root / 'victim'
        victim.write_bytes(b'preserve')
        (destination / self.file.name).symlink_to(victim)
        with self.assertRaises(ValueError):
            custody.finish_fetch(target, digest, self.env)
        self.assertEqual(victim.read_bytes(), b'preserve')
        (destination / self.file.name).unlink()
        custody.finish_fetch(target, digest, self.env)
        self.assertEqual((destination / self.file.name).read_bytes(), self.file.read_bytes())
        self.assertIn('images=\n', (self.root / 'output').read_text())


if __name__ == '__main__':
    unittest.main()
