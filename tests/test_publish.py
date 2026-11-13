"""Real local Git repositories; synthetic records only, no network access."""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dashboard.core import Context, Error, atomic_json, read_json, sha, load_public
from dashboard.engine import approve, import_draft, preview, project_change
from dashboard.initialize import local_init, prepare, bootstrap
from dashboard.publish import publish
from dashboard.gitops import out, git, remote_tip

EMAIL = '12345+synthetic@users.noreply.github.com'
ROOT = Path(__file__).resolve().parents[1]


def draft():
    return {'schema_version': 1, 'draft_id': 'draft_synthetic', 'project_id': 'proj_synthetic',
            'record_type': 'progress', 'occurred_at': '2026-11-12', 'summary': '完成合成验证',
            'state_as_of': None, 'state_snapshot': None, 'source': None,
            'evidence': '合成测试', 'verification': 'confirmed', 'revision': None}


class Crash(BaseException):
    pass


def crash_at(point):
    def fail(stage):
        if stage == point:
            raise Crash(stage)
    return fail


class PublishCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dashboard-git-test-')
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        atomic_json(self.repo / 'public/projects.json', {'schema_version': 1, 'projects': []})
        (self.repo / 'README.md').write_text('Synthetic initialization\n')
        self.ctx = Context(self.repo, self.root / 'private')
        local_init(self.ctx, EMAIL)
        self.base = self.ctx.head()
        self.remote = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', '--initial-branch=main', str(self.remote)], check=True, capture_output=True)
        git(self.ctx, 'remote', 'add', 'origin', str(self.remote))
        self.plan = prepare(self.ctx, self.remote, EMAIL)
        bootstrap(self.ctx, self.plan['digest'])

    def tearDown(self):
        self.temp.cleanup()

    def batch(self, approved=True):
        p = project_change(self.ctx, 'create', 'proj_synthetic', '合成项目', 'research')['draft_id']
        d = import_draft(self.ctx, draft())['draft_id']
        b = preview(self.ctx, [p, d])
        if approved:
            approve(self.ctx, b['batch_id'], b['digest'])
        return b

    def journal(self, b):
        return self.ctx.local / 'transactions' / b['batch_id'] / 'journal.json'

    def test_normal_publish_and_idempotent_retry(self):
        b = self.batch()
        first = publish(self.ctx, b['batch_id'])
        second = publish(self.ctx, b['batch_id'])
        self.assertEqual(first['commit'], second['commit'])
        self.assertTrue(second['already_on_remote'])
        self.assertEqual(out(self.ctx, 'rev-list', '--count', 'HEAD'), '2')
        self.assertEqual(out(self.ctx, 'show', '-s', '--format=%ae'), EMAIL)
        self.assertEqual(out(self.ctx, 'status', '--porcelain'), '')
        self.assertEqual(remote_tip(self.ctx, str(self.remote)), first['commit'])

    def test_unapproved_refused(self):
        b = self.batch(False)
        with self.assertRaises(Error): publish(self.ctx, b['batch_id'])
        self.assertEqual(self.ctx.head(), self.base)

    def test_frozen_or_approval_mutation_refused(self):
        for filename in ('candidate/public/projects.json', 'manifest.json', 'preview.md', 'approval.json'):
            with self.subTest(filename=filename):
                b = self.batch()
                target = self.ctx.local / 'approvals' / b['batch_id'] / filename
                original = target.read_bytes()
                target.write_bytes(original + b' ')
                with self.assertRaises(Error): publish(self.ctx, b['batch_id'])
                target.write_bytes(original)
        self.assertEqual(self.ctx.head(), self.base)

    def test_precommit_crash_points_restore_and_retry(self):
        for point in ('before_write', 'after_file_0', 'after_file_1', 'after_write', 'after_stage', 'before_commit'):
            with self.subTest(point=point):
                b = self.batch()
                with self.assertRaises(Crash): publish(self.ctx, b['batch_id'], _fault=crash_at(point))
                self.assertEqual(self.ctx.head(), self.base)
                result = publish(self.ctx, b['batch_id'], recover_only=True)
                self.assertEqual(result['status'], 'rolled_back')
                self.assertEqual(load_public(self.repo), ([], []))
                self.assertEqual(out(self.ctx, 'status', '--porcelain'), '')
        # Final recovered batch can be prepared again, without losing approval.
        self.assertEqual(publish(self.ctx, b['batch_id'])['status'], 'pushed')

    def test_real_process_exit_after_stage(self):
        b = self.batch()
        program = '''from pathlib import Path
import os,sys
from dashboard.core import Context
from dashboard.publish import publish
ctx=Context(Path(sys.argv[1]),Path(sys.argv[2]))
def fail(stage):
    if stage=='after_stage': os._exit(73)
publish(ctx,sys.argv[3],_fault=fail)
'''
        p = subprocess.run([os.sys.executable, '-c', program, str(self.repo), str(self.ctx.local), b['batch_id']], cwd=ROOT, capture_output=True)
        self.assertEqual(p.returncode, 73, p.stderr)
        self.assertEqual(publish(self.ctx, b['batch_id'], True)['status'], 'rolled_back')
        self.assertEqual(publish(self.ctx, b['batch_id'])['status'], 'pushed')

    def test_commit_success_before_journal_is_recovered(self):
        b = self.batch()
        with self.assertRaises(Crash): publish(self.ctx, b['batch_id'], _fault=crash_at('after_commit'))
        commit = self.ctx.head()
        self.assertNotEqual(commit, self.base)
        self.assertEqual(read_json(self.journal(b))['state'], 'commit_ready')
        self.assertEqual(publish(self.ctx, b['batch_id'])['commit'], commit)
        self.assertEqual(out(self.ctx, 'rev-list', '--count', 'HEAD'), '2')

    def test_commit_object_before_branch_update_is_reused(self):
        b = self.batch()
        with self.assertRaises(Crash): publish(self.ctx, b['batch_id'], _fault=crash_at('after_commit_object'))
        journal = read_json(self.journal(b))
        self.assertEqual(self.ctx.head(), self.base)
        self.assertEqual(journal['state'], 'commit_ready')
        self.assertEqual(publish(self.ctx, b['batch_id'])['commit'], journal['commit'])

    def test_candidate_changed_inside_transaction_stops_before_commit(self):
        b = self.batch()
        def mutate(stage):
            if stage == 'before_commit':
                target = self.ctx.local / 'approvals' / b['batch_id'] / 'preview.md'
                target.write_bytes(target.read_bytes() + b'changed')
        with self.assertRaises(Error): publish(self.ctx, b['batch_id'], _fault=mutate)
        self.assertEqual(self.ctx.head(), self.base)

    def test_wrong_branch_and_hidden_index_flags_refused(self):
        b = self.batch()
        git(self.ctx, 'switch', '-c', 'other')
        with self.assertRaises(Error): publish(self.ctx, b['batch_id'])
        git(self.ctx, 'switch', 'main')
        git(self.ctx, 'update-index', '--assume-unchanged', 'README.md')
        with self.assertRaises(Error): publish(self.ctx, b['batch_id'])

    def test_backup_tampering_stops_recovery(self):
        b = self.batch()
        with self.assertRaises(Crash): publish(self.ctx, b['batch_id'], _fault=crash_at('after_write'))
        backup = self.journal(b).parent / 'backup/public/projects.json'
        backup.write_text('tampered backup')
        before = (self.repo / 'public/projects.json').read_bytes()
        with self.assertRaises(Error): publish(self.ctx, b['batch_id'], True)
        self.assertEqual((self.repo / 'public/projects.json').read_bytes(), before)

    def test_external_staging_during_recovery_is_not_removed(self):
        b = self.batch()
        with self.assertRaises(Crash): publish(self.ctx, b['batch_id'], _fault=crash_at('after_stage'))
        (self.repo / 'README.md').write_text('external staging')
        git(self.ctx, 'add', 'README.md')
        before = out(self.ctx, 'write-tree')
        with self.assertRaises(Error): publish(self.ctx, b['batch_id'], True)
        self.assertEqual(out(self.ctx, 'write-tree'), before)

    def test_commit_blob_or_mode_mismatch_not_recovered(self):
        b = self.batch()
        with self.assertRaises(Crash): publish(self.ctx, b['batch_id'], _fault=crash_at('after_stage'))
        (self.repo / 'public/projects.json').chmod(0o755)
        git(self.ctx, 'add', 'public/projects.json')
        git(self.ctx, '-c', 'user.name=Synthetic', '-c', f'user.email={EMAIL}', 'commit', '-m',
            'Progress-Batch: ' + b['batch_id'])
        with self.assertRaises(Error): publish(self.ctx, b['batch_id'])

    def test_missing_journal_after_commit_is_reconstructed(self):
        b = self.batch()
        with self.assertRaises(Crash): publish(self.ctx, b['batch_id'], _fault=crash_at('after_commit'))
        self.journal(b).unlink()
        self.assertEqual(publish(self.ctx, b['batch_id'])['status'], 'pushed')

    def test_push_success_before_journal_recognized(self):
        b = self.batch()
        with self.assertRaises(Crash): publish(self.ctx, b['batch_id'], _fault=crash_at('after_push'))
        with patch('dashboard.publish.push', side_effect=AssertionError('must not push again')):
            self.assertTrue(publish(self.ctx, b['batch_id'])['already_on_remote'])

    def test_rejected_push_retries_without_duplicate_commit(self):
        b = self.batch()
        hook = self.remote / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        with self.assertRaises(Error): publish(self.ctx, b['batch_id'])
        commit = self.ctx.head()
        hook.unlink()
        self.assertEqual(publish(self.ctx, b['batch_id'])['commit'], commit)
        self.assertEqual(out(self.ctx, 'rev-list', '--count', 'HEAD'), '2')

    def test_unknown_push_result_queries_remote(self):
        b = self.batch()
        from dashboard.gitops import push as real_push
        def ambiguous(*args):
            real_push(*args)
            return False
        with patch('dashboard.publish.push', side_effect=ambiguous):
            self.assertEqual(publish(self.ctx, b['batch_id'])['status'], 'pushed')

    def test_network_unavailable_after_commit_can_retry(self):
        b = self.batch()
        with self.assertRaises(Crash): publish(self.ctx, b['batch_id'], _fault=crash_at('before_push'))
        commit = self.ctx.head()
        hidden = self.remote.with_name('offline.git')
        self.remote.rename(hidden)
        with self.assertRaises(Error): publish(self.ctx, b['batch_id'])
        hidden.rename(self.remote)
        self.assertEqual(publish(self.ctx, b['batch_id'])['commit'], commit)

    def external_commit(self, parent=None):
        tree = out(self.ctx, 'rev-parse', self.base + '^{tree}')
        commit = git(self.ctx, '-c', 'user.name=Synthetic', '-c', f'user.email={EMAIL}', 'commit-tree', tree,
                     '-p', parent or self.base, input=b'Independent synthetic change\n').stdout.decode().strip()
        git(self.ctx, 'push', str(self.remote), commit + ':refs/heads/main')
        return commit

    def test_remote_ahead_before_publish_stops_without_mutation(self):
        b = self.batch()
        remote = self.external_commit()
        with self.assertRaises(Error): publish(self.ctx, b['batch_id'])
        self.assertEqual(self.ctx.head(), self.base)
        self.assertEqual(remote_tip(self.ctx, str(self.remote)), remote)
        self.assertEqual(load_public(self.repo), ([], []))

    def test_remote_conflict_after_commit_preserves_local_commit(self):
        b = self.batch()
        with self.assertRaises(Crash): publish(self.ctx, b['batch_id'], _fault=crash_at('after_commit'))
        commit = self.ctx.head()
        remote = self.external_commit()
        with self.assertRaises(Error): publish(self.ctx, b['batch_id'])
        self.assertEqual(self.ctx.head(), commit)
        self.assertEqual(remote_tip(self.ctx, str(self.remote)), remote)

    def test_remote_descendant_already_contains_commit(self):
        b = self.batch()
        result = publish(self.ctx, b['batch_id'])
        self.external_commit(result['commit'])
        self.assertTrue(publish(self.ctx, b['batch_id'])['already_on_remote'])

    def test_dirty_and_staged_unrelated_changes_stop(self):
        b = self.batch()
        (self.repo / 'README.md').write_text('user edit')
        for staged in (False, True):
            if staged: git(self.ctx, 'add', 'README.md')
            with self.assertRaises(Error): publish(self.ctx, b['batch_id'])
        self.assertEqual((self.repo / 'README.md').read_text(), 'user edit')

    def test_recovery_preserves_external_file_and_index_changes(self):
        b = self.batch()
        with self.assertRaises(Crash): publish(self.ctx, b['batch_id'], _fault=crash_at('after_stage'))
        target = self.repo / 'public/projects.json'
        target.write_text('external edit')
        before_index = out(self.ctx, 'write-tree')
        with self.assertRaises(Error): publish(self.ctx, b['batch_id'], True)
        self.assertEqual(target.read_text(), 'external edit')
        self.assertEqual(out(self.ctx, 'write-tree'), before_index)

    def test_approval_change_during_recovery_refused(self):
        b = self.batch()
        with self.assertRaises(Crash): publish(self.ctx, b['batch_id'], _fault=crash_at('after_stage'))
        receipt = self.ctx.local / 'approvals' / b['batch_id'] / 'approval.json'
        value = read_json(receipt)
        value['approved_at'] = '2026-11-13T00:00:00+08:00'
        atomic_json(receipt, value)
        with self.assertRaises(Error): publish(self.ctx, b['batch_id'], True)

    def test_network_remote_and_changed_origin_refused(self):
        b = self.batch()
        git(self.ctx, 'remote', 'set-url', 'origin', 'https://github.com/example/never-created.git')
        with self.assertRaises(Error): publish(self.ctx, b['batch_id'])
        self.assertEqual(self.ctx.head(), self.base)

    def test_symlink_candidate_refused(self):
        b = self.batch()
        target = self.ctx.local / 'approvals' / b['batch_id'] / 'candidate/public/projects.json'
        data = target.read_bytes()
        target.unlink()
        other = self.root / 'other.json'
        other.write_bytes(data)
        target.symlink_to(other)
        with self.assertRaises(Error): publish(self.ctx, b['batch_id'])

    def test_same_marker_wrong_commit_not_accepted(self):
        b = self.batch()
        git(self.ctx, '-c', 'user.name=Synthetic', '-c', f'user.email={EMAIL}', 'commit', '--allow-empty', '-m',
            'Progress-Batch: ' + b['batch_id'])
        with self.assertRaises(Error): publish(self.ctx, b['batch_id'])

    def test_cross_day_revision_single_commit_deletes_old_bucket(self):
        b = self.batch()
        publish(self.ctx, b['batch_id'])
        old = load_public(self.repo)[1][0]
        value = draft()
        value.update(draft_id='draft_revision', occurred_at='2026-11-13',
                     revision={'target_record_id': old['record_id'], 'correct_occurred_at': True, 'correct_state_as_of': False})
        d = import_draft(self.ctx, value)['draft_id']
        b2 = preview(self.ctx, [d])
        approve(self.ctx, b2['batch_id'], b2['digest'])
        result = publish(self.ctx, b2['batch_id'])
        self.assertFalse((self.repo / 'public/records/2026/11/12.json').exists())
        self.assertTrue((self.repo / 'public/records/2026/11/13.json').exists())
        self.assertEqual(load_public(self.repo)[1][0]['record_id'], old['record_id'])
        self.assertEqual(out(self.ctx, 'rev-list', '--count', 'HEAD'), '3')

    def test_bootstrap_nonempty_and_bad_digest_refused(self):
        with self.assertRaises(Error): prepare(self.ctx, self.remote, EMAIL)
        with self.assertRaises(Error): bootstrap(self.ctx, '0' * 64)
        self.assertTrue(bootstrap(self.ctx, self.plan['digest'])['initialized'])

    def test_bootstrap_success_before_receipt_recovers(self):
        (self.ctx.local / 'publish-config.json').unlink()
        git(self.ctx, '--git-dir=' + str(self.remote), 'update-ref', '-d', 'refs/heads/main')
        with self.assertRaises(Crash): bootstrap(self.ctx, self.plan['digest'], crash_at('after_bootstrap_push'))
        self.assertFalse((self.ctx.local / 'publish-config.json').exists())
        self.assertTrue(bootstrap(self.ctx, self.plan['digest'])['initialized'])

    def test_bootstrap_rejects_existing_readme_history(self):
        self.external_commit()
        with self.assertRaises(Error): bootstrap(self.ctx, self.plan['digest'])

    def test_publish_requires_initialization_receipt(self):
        b = self.batch()
        (self.ctx.local / 'publish-config.json').unlink()
        with self.assertRaises(Error): publish(self.ctx, b['batch_id'])

    def test_bootstrap_rejects_private_file_in_root_history(self):
        # A second commit is itself disallowed, so do not rewrite the bootstrap commit.
        (self.repo / 'secret.local.json').write_text('{}')
        git(self.ctx, 'add', 'secret.local.json')
        git(self.ctx, '-c', 'user.name=Synthetic', '-c', f'user.email={EMAIL}', 'commit', '-m', 'private synthetic file')
        with self.assertRaises(Error): prepare(self.ctx, self.remote, EMAIL)

    def test_fresh_initialization_rejects_nonempty_public_and_non_noreply(self):
        repo = self.root / 'fresh'
        repo.mkdir()
        atomic_json(repo / 'public/projects.json', {'schema_version': 1, 'projects': [
            {'schema_version': 1, 'project_id': 'proj_demo', 'public_name': '合成项目', 'category': 'other', 'aliases': []}]})
        ctx = Context(repo, self.root / 'fresh-private')
        with self.assertRaises(Error): local_init(ctx, EMAIL)
        self.assertFalse((repo / '.git').exists())
        with self.assertRaises(Error): local_init(ctx, 'synthetic@example.test')

    def test_bootstrap_plan_tampering_refused(self):
        plan = read_json(self.ctx.local / 'bootstrap.json')
        plan['email'] = 'different@users.noreply.github.com'
        atomic_json(self.ctx.local / 'bootstrap.json', plan)
        with self.assertRaises(Error): bootstrap(self.ctx, self.plan['digest'])

    def test_explicit_recovery_works_while_remote_is_unavailable(self):
        b = self.batch()
        with self.assertRaises(Crash): publish(self.ctx, b['batch_id'], _fault=crash_at('after_stage'))
        self.remote.rename(self.root / 'offline.git')
        self.assertEqual(publish(self.ctx, b['batch_id'], True)['status'], 'rolled_back')

    def test_public_commit_uses_noreply_despite_local_identity_config(self):
        git(self.ctx, 'config', 'author.email', 'synthetic-private@example.test')
        git(self.ctx, 'config', 'committer.email', 'synthetic-private@example.test')
        b = self.batch()
        publish(self.ctx, b['batch_id'])
        self.assertEqual(out(self.ctx, 'show', '-s', '--format=%ae'), EMAIL)
        self.assertEqual(out(self.ctx, 'show', '-s', '--format=%ce'), EMAIL)

    def test_credential_in_initial_files_rejected_before_git_creation(self):
        repo = self.root / 'fresh'
        repo.mkdir()
        atomic_json(repo / 'public/projects.json', {'schema_version': 1, 'projects': []})
        (repo / 'README.md').write_text('ghp_' + 'x' * 30)
        ctx = Context(repo, self.root / 'fresh-private')
        with self.assertRaises(Error): local_init(ctx, EMAIL)
        self.assertFalse((repo / '.git').exists())
