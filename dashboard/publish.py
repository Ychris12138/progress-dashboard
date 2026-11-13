"""Approval-bound Git transaction. No reset, stash, rebase, force push or network remote."""
from __future__ import annotations

import os
from pathlib import Path

from .core import (atomic_bytes, atomic_json, canonical, no_links, now, obj, public_path,
                   read_json, reject_tree_links, require, sha, temporal)
from .engine import source_files, verify_batch, verify_frozen
from .gitops import clean, contains, git, local_remote, noreply, out, push, remote_tip, repo_lock, repository
from .initialize import enabled


def changed(ctx, *args):
    return set(x.decode() for x in git(ctx, 'diff', '--no-renames', '--name-only', '-z', *args).stdout.split(b'\0') if x)


def blob(ctx, ref, path):
    proc = git(ctx, 'show', f'{ref}:{path}', check=False)
    return proc.stdout if proc.returncode == 0 else None


def digest(data):
    return sha(data) if data is not None else None


def approval(batch, batch_id, manifest_digest):
    receipt = read_json(batch / 'approval.json')
    obj(receipt, ['schema_version', 'batch_id', 'manifest_sha256', 'approved_at'], 'approval receipt')
    require(receipt['schema_version'] == 1 and receipt['batch_id'] == batch_id and
            receipt['manifest_sha256'] == manifest_digest, 'batch is not approved for this digest')
    temporal(receipt['approved_at'], exact=True)
    raw = (batch / 'approval.json').read_bytes()
    require(raw == canonical(receipt), 'approval serialization changed')
    return sha(raw)


def verify_commit(ctx, commit, manifest):
    base = manifest['base_commit']
    parents = out(ctx, 'rev-list', '--parents', '-n', '1', commit).split()
    require(parents == [commit, base], 'recovery commit must have the exact approved parent')
    for field in ('%ae', '%ce'):
        noreply(out(ctx, 'show', '-s', '--format=' + field, commit))
    message = out(ctx, 'show', '-s', '--format=%B', commit)
    require(message.splitlines().count('Progress-Batch: ' + manifest['batch_id']) == 1,
            'recovery commit batch marker mismatch')
    operations = {op['path']: op for op in manifest['operations']}
    require(changed(ctx, base, commit) == set(operations), 'commit changed file set differs from approval')
    # Changes to executable bits/symlinks are not part of approved public JSON operations.
    for path, operation in operations.items():
        raw = blob(ctx, commit, path)
        require(digest(raw) == operation['new_sha256'], 'commit blob differs from frozen candidate')
        if raw is not None:
            require(out(ctx, 'ls-tree', commit, '--', path).startswith('100644 blob '), 'invalid committed file mode')
    return commit


def verify_base(ctx, manifest):
    base = manifest['base_commit']
    require(base, 'batch has no initialized Git base')
    for path, expected in manifest['base_public'].items():
        require(digest(blob(ctx, base, path)) == expected, 'approved public baseline is not committed')


def current(path):
    path = no_links(path)
    require(not path.exists() or path.is_file(), 'expected ordinary file')
    return path.read_bytes() if path.exists() else None


def save(tx, journal, state, **fields):
    journal.update(fields)
    journal['state'] = state
    journal['events'].append({'state': state, 'at': now()})
    atomic_json(tx / 'journal.json', journal)


def validate_journal(journal):
    obj(journal, ['schema_version', 'batch_id', 'manifest_sha256', 'approval_sha256',
                  'base_commit', 'commit', 'state', 'events'], 'transaction journal')
    require(journal['schema_version'] == 1 and journal['state'] in
            ('prepared', 'commit_ready', 'committed', 'pushed', 'push_pending', 'rolled_back'), 'invalid transaction state')
    require(type(journal['events']) is list, 'invalid transaction events')
    for event in journal['events']:
        obj(event, ['state', 'at'], 'transaction event')
        temporal(event['at'], exact=True)


def verify_index(ctx, manifest):
    operations = manifest['operations']
    require(changed(ctx, '--cached', manifest['base_commit']) == {op['path'] for op in operations},
            'staged files differ from approved operations')
    for op in operations:
        require(digest(blob(ctx, '', op['path'])) == op['new_sha256'], 'staged blob differs from approval')
    # write-tree confirms there are no unmerged entries; verify modes on staged files too.
    tree = out(ctx, 'write-tree')
    for op in operations:
        if op['new_sha256'] is not None:
            require(out(ctx, 'ls-tree', tree, '--', op['path']).startswith('100644 blob '), 'staged file mode differs')
    return tree


def recover_before_commit(ctx, tx, journal, manifest):
    """Validate every involved file and index entry before undoing any of them."""
    require(ctx.head() == manifest['base_commit'], 'HEAD moved; precommit rollback refused')
    operations = {op['path']: op for op in manifest['operations']}
    staged = changed(ctx, '--cached', manifest['base_commit'])
    unstaged = changed(ctx)
    untracked = {p.decode() for p in git(ctx, 'ls-files', '--others', '--exclude-standard', '-z').stdout.split(b'\0') if p}
    require((staged | unstaged | untracked) <= set(operations), 'external worktree/index changes; recovery stopped')
    for path, op in operations.items():
        require(digest(current(public_path(ctx.repo, path))) in (op['old_sha256'], op['new_sha256']),
                'external file edit; recovery stopped without overwriting')
        require(digest(blob(ctx, '', path)) in (op['old_sha256'], op['new_sha256']),
                'external index edit; recovery stopped without unstaging')
        if op['old_sha256'] is not None:
            require(digest(current(public_path(tx / 'backup', path))) == op['old_sha256'], 'backup changed')
    if staged:
        git(ctx, 'restore', '--staged', '--source=' + manifest['base_commit'], '--', *sorted(staged))
    for path, op in operations.items():
        target = public_path(ctx.repo, path)
        if op['old_sha256'] is None:
            if target.exists():
                target.unlink()
        else:
            atomic_bytes(target, public_path(tx / 'backup', path).read_bytes())
    clean(ctx)
    save(tx, journal, 'rolled_back')
    return {'batch_id': manifest['batch_id'], 'status': 'rolled_back', 'retry': 'repeat publish to prepare again'}


def publish(ctx, batch_id, recover_only=False, _fault=lambda stage: None):
    with ctx.lock(), repo_lock(ctx):
        repository(ctx)
        config = enabled(ctx, offline=recover_only)
        batch, manifest, seal = verify_frozen(ctx, batch_id)
        receipt_hash = approval(batch, batch_id, seal)
        def recheck_approval():
            verify_frozen(ctx, batch_id, seal)
            require(approval(batch, batch_id, seal) == receipt_hash, 'approval changed during transaction')
            require(manifest['target'] == ctx.target(), 'target changed during transaction')
        require(manifest['target'] == ctx.target(), 'approved remote/branch changed')
        remote = local_remote(ctx, manifest['target']['repository'], offline=recover_only)
        verify_base(ctx, manifest)
        tx = no_links(ctx.local / 'transactions' / batch_id)
        reject_tree_links(tx)
        journal_path = tx / 'journal.json'
        journal = read_json(journal_path) if journal_path.exists() else None
        if journal is not None:
            validate_journal(journal)
            require(journal['batch_id'] == batch_id and journal['manifest_sha256'] == seal and
                    journal['approval_sha256'] == receipt_hash and journal['base_commit'] == manifest['base_commit'],
                    'transaction approval/baseline changed')
        else:
            journal = {'schema_version': 1, 'batch_id': batch_id, 'manifest_sha256': seal,
                       'approval_sha256': receipt_hash, 'base_commit': manifest['base_commit'],
                       'commit': None, 'state': 'new', 'events': []}
        head = ctx.head()
        if head != manifest['base_commit']:
            # Includes commit success before journal update, or journal loss. No commit creation here.
            commit = verify_commit(ctx, head, manifest)
            require(journal['commit'] in (None, commit), 'transaction commit differs from HEAD')
            clean(ctx)
            save(tx, journal, 'committed', commit=commit)
        elif journal['state'] == 'commit_ready':
            commit = verify_commit(ctx, journal['commit'], manifest)
            verify_index(ctx, manifest)
            require(not changed(ctx) and not git(ctx, 'ls-files', '--others', '--exclude-standard').stdout,
                    'external edits after commit object creation; recovery stopped')
            recheck_approval()
            git(ctx, 'update-ref', '-m', 'Progress-Batch: ' + batch_id, 'refs/heads/main', commit, head)
            save(tx, journal, 'committed', commit=commit)
            clean(ctx)
        elif journal['state'] == 'prepared':
            return recover_before_commit(ctx, tx, journal, manifest)
        else:
            require(journal['commit'] is None, 'committed transaction HEAD changed; never reset automatically')
            if recover_only:
                return {'batch_id': batch_id, 'status': 'nothing_to_recover'}
            verify_batch(ctx, batch_id, seal)
            clean(ctx)
            require(remote_tip(ctx, remote) == head, 'remote is ahead, divergent or missing; fresh review required')
            # Write-ahead backups are immutable and verified before the prepared journal is durable.
            for op in manifest['operations']:
                if op['old_sha256'] is not None:
                    raw = current(public_path(ctx.repo, op['path']))
                    require(digest(raw) == op['old_sha256'], 'old file changed')
                    atomic_bytes(public_path(tx / 'backup', op['path']), raw)
            save(tx, journal, 'prepared')
            _fault('before_write')
            for index, op in enumerate(manifest['operations']):
                target = public_path(ctx.repo, op['path'])
                require(digest(current(target)) == op['old_sha256'], 'concurrent file edit; transaction stopped')
                if op['new_sha256'] is None:
                    target.unlink()
                else:
                    atomic_bytes(target, public_path(batch / 'candidate', op['path']).read_bytes())
                    target.chmod(0o644)
                _fault(f'after_file_{index}')
            _fault('after_write')
            require({p: sha(b) for p, b in source_files(ctx.repo).items()} == manifest['files'], 'candidate application differs')
            # Detect outside staging before adding exactly this operation list.
            require(not changed(ctx, '--cached', head), 'external staging detected')
            git(ctx, 'add', '--', *(op['path'] for op in manifest['operations']))
            _fault('after_stage')
            tree = verify_index(ctx, manifest)
            require(ctx.head() == head, 'HEAD changed before commit')
            _fault('before_commit')
            recheck_approval()
            # commit-tree binds the verified tree even if another process races the index.
            msg = f'Publish approved progress\n\nProgress-Batch: {batch_id}\n'
            commit = git(ctx, '-c', 'user.name=Progress Dashboard', '-c', f'user.email={config["email"]}',
                         '-c', 'commit.gpgSign=false', 'commit-tree', tree, '-p', head,
                         input=msg.encode(), dates=manifest['created_at'], identity=config['email']).stdout.decode().strip()
            verify_commit(ctx, commit, manifest)
            # Fixed approved timestamp makes object creation idempotent even if this journal write is interrupted.
            save(tx, journal, 'commit_ready', commit=commit)
            _fault('after_commit_object')
            git(ctx, 'update-ref', '-m', 'Progress-Batch: ' + batch_id, 'refs/heads/main', commit, head)
            _fault('after_commit')
            save(tx, journal, 'committed', commit=commit)
            clean(ctx)
        if recover_only:
            return {'batch_id': batch_id, 'status': 'committed', 'commit': commit}
        recheck_approval()
        # Always query remote before any retry; a successful-but-unacknowledged push is success.
        if contains(ctx, remote, commit):
            save(tx, journal, 'pushed', commit=commit)
            return {'batch_id': batch_id, 'status': 'pushed', 'commit': commit, 'already_on_remote': True}
        require(remote_tip(ctx, remote) == manifest['base_commit'],
                'remote conflict after commit; commit and evidence retained; no automatic rebase/reset')
        _fault('before_push')
        recheck_approval()
        push(ctx, remote, commit)
        _fault('after_push')
        if contains(ctx, remote, commit):
            save(tx, journal, 'pushed', commit=commit)
            return {'batch_id': batch_id, 'status': 'pushed', 'commit': commit, 'already_on_remote': False}
        save(tx, journal, 'push_pending', commit=commit)
        require(False, 'push failed or result unknown; commit retained, repeat publish to query then retry')
