"""Repeatable synthetic-only exercise. Retains local bare repository and failure evidence."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.core import Context, Error, atomic_json, canonical, no_links, require
from dashboard.engine import approve, import_draft, preview, project_change
from dashboard.initialize import local_init, prepare, bootstrap
from dashboard.publish import publish
from dashboard.gitops import git, out, remote_tip


class InjectedCrash(BaseException):
    pass


def run(output):
    root = no_links(output).resolve()
    require(not root.exists(), 'demo output must be a new directory')
    source = Path(__file__).resolve().parents[1]
    require(not root.is_relative_to(source), 'demo must be outside source repository')
    root.mkdir(parents=True, mode=0o700)
    repo = root / 'repo'
    repo.mkdir()
    atomic_json(repo / 'public/projects.json', {'schema_version': 1, 'projects': []})
    (repo / 'README.md').write_text('Synthetic local Git transaction demonstration. Never deploy.\n')
    ctx = Context(repo, root / 'private')
    email = '12345+synthetic@users.noreply.github.com'
    local_init(ctx, email)
    remote = root / 'remote.git'
    git(ctx, 'init', '--bare', '--initial-branch=main', str(remote))
    git(ctx, 'remote', 'add', 'origin', str(remote))
    plan = prepare(ctx, remote, email)
    bootstrap(ctx, plan['digest'])
    initial = ctx.head()
    p = project_change(ctx, 'create', 'proj_demo', '合成发布演示', 'other')['draft_id']
    raw = {'schema_version': 1, 'draft_id': 'draft_demo', 'project_id': 'proj_demo', 'record_type': 'progress',
           'occurred_at': '2026-11-13', 'summary': '完成合成发布验证', 'state_as_of': None, 'state_snapshot': None,
           'source': None, 'evidence': '固定的合成演示输入', 'verification': 'confirmed', 'revision': None}
    d = import_draft(ctx, raw)['draft_id']
    b = preview(ctx, [p, d])
    # Only this fixed synthetic dataset is automatically approved by the demonstration.
    approve(ctx, b['batch_id'], b['digest'])
    def crash(stage):
        if stage == 'after_stage':
            raise InjectedCrash(stage)
    try:
        publish(ctx, b['batch_id'], _fault=crash)
    except InjectedCrash:
        pass
    recovered = publish(ctx, b['batch_id'], recover_only=True)
    require(recovered['status'] == 'rolled_back' and ctx.head() == initial, 'rollback verification failed')
    hook = remote / 'hooks/pre-receive'
    hook.write_text('#!/bin/sh\nexit 1\n')
    hook.chmod(0o755)
    try:
        publish(ctx, b['batch_id'])
    except Error as exc:
        rejection = str(exc)
    else:
        raise Error('receiver unexpectedly accepted rejected push')
    commit = ctx.head()
    require(commit != initial and remote_tip(ctx, str(remote)) == initial, 'failed push did not retain commit')
    hook.rename(remote / 'hooks/pre-receive.rejected-example')
    result = publish(ctx, b['batch_id'])
    require(result['commit'] == commit, 'retry duplicated commit')
    repeated = publish(ctx, b['batch_id'])
    require(repeated['already_on_remote'], 'idempotent retry failed')
    # Preserve a second committed batch whose push is blocked by a remote fork.
    p2 = project_change(ctx, 'rename', 'proj_demo', '合成发布演示二')['draft_id']
    b2 = preview(ctx, [p2])
    approve(ctx, b2['batch_id'], b2['digest'])
    def stop_after_commit(stage):
        if stage == 'after_commit':
            raise InjectedCrash(stage)
    try:
        publish(ctx, b2['batch_id'], _fault=stop_after_commit)
    except InjectedCrash:
        pass
    retained = ctx.head()
    tree = out(ctx, 'rev-parse', commit + '^{tree}')
    fork = git(ctx, '-c', 'user.name=Synthetic', '-c', f'user.email={email}', 'commit-tree', tree,
               '-p', commit, input=b'Independent synthetic remote change\n').stdout.decode().strip()
    git(ctx, 'push', str(remote), fork + ':refs/heads/main')
    try:
        publish(ctx, b2['batch_id'])
    except Error as exc:
        conflict = str(exc)
    else:
        raise Error('remote conflict was not detected')
    require(ctx.head() == retained and remote_tip(ctx, str(remote)) == fork, 'conflict modified history')
    proof = {'synthetic_only': True, 'bootstrap_commit': initial, 'published_commit': commit,
             'publish_batch': b['batch_id'], 'recovered': recovered, 'push_rejection': rejection,
             'duplicate_commit': False, 'conflict_batch': b2['batch_id'], 'retained_commit': retained,
             'remote_fork': fork, 'conflict': conflict, 'remote_created': 'local-bare-only',
             'github_created': False, 'pages_deployed': False}
    atomic_json(root / 'proof.json', proof)
    return {'proof': str(root / 'proof.json'), 'repository': str(repo), 'remote': str(remote),
            'transactions': str(ctx.local / 'transactions'), 'status': 'verified; conflict evidence retained'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(canonical(run(args.output)).decode(), end='')
    except (Error, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
