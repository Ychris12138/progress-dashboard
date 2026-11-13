"""Separate, digest-bound initialization for disposable local bare remotes."""
from pathlib import Path
import re

from .core import (atomic_json, canonical, fingerprint, load_public, no_links, now,
                   obj, read_json, reject_tree_links, require, sha)
from .gitops import clean, git, local_remote, noreply, out, push, remote_refs, remote_tip, repo_lock, repository

TOP = {'AGENTS.md', 'README.md', '.gitignore', 'pyproject.toml', 'package.json', 'package-lock.json'}
DIRS = {'dashboard', 'scripts', 'schemas', 'src', 'tests', 'docs', 'public', '.github'}


def credential_check(data):
    require(not re.search(rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY)', data),
            'credential pattern in bootstrap tree')


def allowed(path):
    p = Path(path)
    return (path in TOP or (len(p.parts) > 1 and p.parts[0] in DIRS)) and not any(
        x.startswith('.') and x not in ('.github', '.gitignore', '.gitkeep') or
        x in ('__pycache__', 'node_modules', 'source-cache', 'checkpoints', 'approvals') or
        x.endswith(('.pyc', '.local.json')) for x in p.parts)


def empty_data(ctx):
    require(load_public(ctx.repo) == ([], []), 'bootstrap requires empty public business data')


def audit_tree(ctx):
    require(out(ctx, 'rev-list', '--count', 'HEAD') == '1', 'bootstrap requires exactly one root commit')
    empty_data(ctx)
    result = {}
    for entry in git(ctx, 'ls-tree', '-r', '-z', 'HEAD').stdout.split(b'\0'):
        if not entry:
            continue
        header, rawpath = entry.split(b'\t', 1)
        mode, kind, oid = header.decode().split()
        path = rawpath.decode()
        require(mode in ('100644', '100755') and kind == 'blob' and allowed(path), 'bootstrap tree outside code allowlist')
        data = git(ctx, 'cat-file', 'blob', oid).stdout
        credential_check(data)
        result[path] = sha(data)
    require('public/projects.json' in result, 'missing tracked empty registry')
    return result


def local_init(ctx, email):
    """Explicit local Git creation; does not add a remote or access a network."""
    noreply(email)
    with ctx.lock():
        require(not (ctx.repo / '.git').exists() and ctx.git('rev-parse', '--show-toplevel') is None,
                'local-init requires a directory outside an existing Git worktree')
        empty_data(ctx)
        files = []
        for name in sorted(TOP | DIRS):
            root = no_links(ctx.repo / name)
            if not root.exists():
                continue
            reject_tree_links(root)
            for path in ([root] if root.is_file() else sorted(root.rglob('*'))):
                if path.is_file() and allowed(path.relative_to(ctx.repo).as_posix()):
                    credential_check(path.read_bytes())
                    files.append(path.relative_to(ctx.repo).as_posix())
        require(files, 'no initialization files')
        git(ctx, 'init', '--initial-branch=main')
        git(ctx, 'add', '--', *files)
        git(ctx, '-c', 'user.name=Progress Dashboard', '-c', f'user.email={email}',
            'commit', '--no-gpg-sign', '-m', 'Initialize empty progress dashboard', identity=email)
        audit_tree(ctx)
        return {'initialized': True, 'commit': ctx.head(), 'remote_created': False}


def prepare(ctx, remote, email):
    noreply(email)
    with ctx.lock(), repo_lock(ctx):
        repository(ctx)
        clean(ctx)
        # Origin must be configured explicitly; preparation never changes Git configuration.
        target = local_remote(ctx, str(no_links(remote).resolve()))
        require(not remote_refs(ctx, target), 'bootstrap remote must be completely empty')
        value = {'schema_version': 1, 'mode': 'local-bare-test', 'repository': str(ctx.repo),
                 'remote': target, 'branch': 'main', 'base_commit': ctx.head(), 'email': email,
                 'files': audit_tree(ctx), 'created_at': now()}
        digest = fingerprint(value)
        atomic_json(ctx.local / 'bootstrap.json', value)
        return {'digest': digest, 'manifest': str(ctx.local / 'bootstrap.json'),
                'review_required': True, 'github_verified': False, 'pages_verified': False}


def bootstrap(ctx, digest, _fault=lambda stage: None):
    with ctx.lock(), repo_lock(ctx):
        repository(ctx)
        clean(ctx)
        value = read_json(ctx.local / 'bootstrap.json')
        obj(value, ['schema_version', 'mode', 'repository', 'remote', 'branch', 'base_commit',
                    'email', 'files', 'created_at'], 'bootstrap manifest')
        require((ctx.local / 'bootstrap.json').read_bytes() == canonical(value), 'bootstrap serialization changed')
        require(fingerprint(value) == digest, 'bootstrap approval digest mismatch')
        require(value['mode'] == 'local-bare-test' and value['repository'] == str(ctx.repo), 'bootstrap context changed')
        require(ctx.head() == value['base_commit'] and audit_tree(ctx) == value['files'], 'bootstrap files/HEAD changed')
        remote = local_remote(ctx, value['remote'])
        refs = remote_refs(ctx, remote)
        # If push succeeded but its receipt was lost, the exact single remote ref proves completion.
        require(not refs or refs == {'refs/heads/main': ctx.head()}, 'remote is not empty or exact bootstrap result')
        if not refs:
            _fault('before_bootstrap_push')
            require(fingerprint(read_json(ctx.local / 'bootstrap.json')) == digest, 'bootstrap approval changed')
            push(ctx, remote, ctx.head())
            _fault('after_bootstrap_push')
            require(remote_refs(ctx, remote) == {'refs/heads/main': ctx.head()},
                    'bootstrap push failed or changed; repeat the same approved bootstrap to query outcome')
        config = {'schema_version': 1, 'mode': 'local-bare-test', 'repository': str(ctx.repo),
                  'remote': remote, 'branch': 'main', 'bootstrap_commit': ctx.head(),
                  'email': noreply(value['email']), 'bootstrap_digest': digest,
                  'github_verified': False, 'pages_verified': False}
        atomic_json(ctx.local / 'publish-config.json', config)
        return {'initialized': True, 'enabled': 'local-bare-test-only', 'commit': ctx.head(),
                'github_verified': False, 'pages_verified': False}


def enabled(ctx, offline=False):
    value = read_json(ctx.local / 'publish-config.json')
    obj(value, ['schema_version', 'mode', 'repository', 'remote', 'branch', 'bootstrap_commit',
                'email', 'bootstrap_digest', 'github_verified', 'pages_verified'], 'publish config')
    require(value['schema_version'] == 1 and value['mode'] == 'local-bare-test' and
            value['repository'] == str(ctx.repo) and value['branch'] == 'main', 'publishing is not initialized for this repository')
    noreply(value['email'])
    require(git(ctx, 'merge-base', '--is-ancestor', value['bootstrap_commit'], 'HEAD', check=False).returncode == 0,
            'bootstrap commit no longer in history')
    local_remote(ctx, value['remote'], offline=offline)
    return value
