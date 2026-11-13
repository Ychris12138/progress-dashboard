"""Local bare transport and guarded Git operations. Network transports are disabled."""
from __future__ import annotations

import contextlib
import fcntl
import os
from pathlib import Path
import re
import subprocess

from .core import Error, no_links, require


def git(ctx, *args, input=None, check=True, transport=False, dates=None, identity=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1')
    if dates is not None:
        env.update(GIT_AUTHOR_DATE=dates, GIT_COMMITTER_DATE=dates)
    if identity is not None:
        noreply(identity)
        env.update(GIT_AUTHOR_NAME='Progress Dashboard', GIT_COMMITTER_NAME='Progress Dashboard',
                   GIT_AUTHOR_EMAIL=identity, GIT_COMMITTER_EMAIL=identity)
    hooks = [] if transport else ['-c', 'core.hooksPath=/dev/null']
    proc = subprocess.run(['git', '-C', str(ctx.repo), *hooks,
                           '-c', 'protocol.allow=never', '-c', 'protocol.file.allow=always',
                           *args], input=input, capture_output=True, env=env)
    if check and proc.returncode:
        # Git stderr may contain configured URLs or private paths; keep CLI errors terse.
        raise Error(f'Git {args[0]} failed (exit {proc.returncode}); transaction preserved')
    return proc


def out(ctx, *args):
    return git(ctx, *args).stdout.decode().strip()


def noreply(email):
    require(type(email) is str and re.fullmatch(r'[A-Za-z0-9+_.-]+@users\.noreply\.github\.com', email),
            'a GitHub noreply email is required')
    return email


def repository(ctx):
    require(ctx.head() is not None and out(ctx, 'rev-parse', '--show-toplevel') == str(ctx.repo),
            'initialize this repository first')
    require(out(ctx, 'symbolic-ref', '--short', 'HEAD') == 'main', 'must be on main')
    # Ignored index flags can conceal edits from status; refuse rather than clear them.
    flags = git(ctx, 'ls-files', '-v', '-z').stdout.split(b'\0')
    require(all(not x or x[:1] == b'H' for x in flags), 'unsupported index flags or conflicts')
    for marker in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply'):
        path = Path(out(ctx, 'rev-parse', '--git-path', marker))
        require(not (ctx.repo / path).exists(), 'Git operation in progress')


@contextlib.contextmanager
def repo_lock(ctx):
    directory = no_links(Path(out(ctx, 'rev-parse', '--absolute-git-dir')))
    with no_links(directory / 'progress-dashboard.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def clean(ctx):
    require(not git(ctx, 'status', '--porcelain=v1', '--untracked-files=all').stdout,
            'worktree/index must be clean; no automatic stash, rebase or reset')


def local_remote(ctx, expected=None, offline=False):
    urls = out(ctx, 'remote', 'get-url', '--all', 'origin').splitlines()
    pushes = out(ctx, 'remote', 'get-url', '--push', '--all', 'origin').splitlines()
    require(len(urls) == 1 and pushes == urls, 'origin must have one identical fetch/push URL')
    raw = urls[0]
    require(raw.startswith('/') and '\n' not in raw, 'phase three accepts only an absolute local bare path')
    remote = no_links(raw).resolve()
    require(str(remote) == raw and (offline or remote.is_dir()), 'remote must be a canonical existing directory')
    require(not remote.is_relative_to(ctx.repo) and not ctx.repo.is_relative_to(remote), 'remote/repo overlap')
    require(not remote.is_relative_to(ctx.local) and not ctx.local.is_relative_to(remote), 'remote/private overlap')
    if expected is not None:
        require(raw == expected, 'remote target changed')
    if not offline:
        require(out(ctx, '--git-dir=' + raw, 'rev-parse', '--is-bare-repository') == 'true', 'remote is not bare')
        require(out(ctx, '--git-dir=' + raw, 'symbolic-ref', 'HEAD') == 'refs/heads/main', 'bare default branch must be main')
    return raw


def remote_refs(ctx, remote):
    lines = out(ctx, 'ls-remote', '--refs', remote).splitlines()
    return {line.split('\t')[1]: line.split('\t')[0] for line in lines}


def remote_tip(ctx, remote):
    return remote_refs(ctx, remote).get('refs/heads/main')


def contains(ctx, remote, commit):
    tip = remote_tip(ctx, remote)
    if tip is None:
        return False
    git(ctx, 'fetch', '--no-tags', '--no-write-fetch-head', remote,
        '+refs/heads/main:refs/progress-dashboard/observed-main')
    # Test the fetched tip; a subsequent push race is resolved by normal Git fast-forward checks.
    return git(ctx, 'merge-base', '--is-ancestor', commit,
               'refs/progress-dashboard/observed-main', check=False).returncode == 0


def push(ctx, remote, commit):
    # --no-verify skips only the sender's pre-push hook. Never disable receiver hooks.
    return git(ctx, 'push', '--no-verify', '--porcelain', remote, f'{commit}:refs/heads/main',
               check=False, transport=True).returncode == 0
