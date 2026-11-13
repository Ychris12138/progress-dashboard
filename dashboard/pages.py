"""Fail-closed Pages eligibility checks. GitHub token is never persisted or printed."""
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request

from .core import Error, load_public, require


def eligible(event, ref):
    return event in ('push', 'workflow_dispatch') and ref == 'refs/heads/main'


def decision(current, main, successful, ancestor):
    if current != main:
        return False, 'superseded-main'
    for previous in successful:
        if previous == current:
            continue
        if ancestor(current, previous):
            return False, 'newer-successful-deployment'
        require(ancestor(previous, current), 'deployed history diverges; refuse automatic replacement')
    return True, 'current-main'


def assert_empty(repo):
    require(load_public(Path(repo)) == ([], []), 'empty-site deployment only: business data is not enabled')


def api(path):
    require(path.startswith('/repos/'), 'unexpected API route')
    request = urllib.request.Request('https://api.github.com' + path, headers={
        'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
        'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def pages(path):
    separator = '&' if '?' in path else '?'
    for page in range(1, 101):
        values = api(f'{path}{separator}per_page=100&page={page}')
        require(type(values) is list, 'unexpected API pagination')
        yield from values
        if len(values) < 100:
            return
    raise Error('deployment history exceeds bounded audit; review required')


def guard():
    if not eligible(os.environ['GITHUB_EVENT_NAME'], os.environ['GITHUB_REF']):
        return False, 'event-or-branch-not-allowed'
    repo = os.environ['GITHUB_REPOSITORY']
    require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo), 'invalid repository')
    current = os.environ['GITHUB_SHA']
    main = api(f'/repos/{repo}/git/ref/heads/main')['object']['sha']
    if current != main:
        return False, 'superseded-main'
    successful = []
    for deployment in pages(f'/repos/{repo}/deployments?environment=github-pages'):
        states = pages(f'/repos/{repo}/deployments/{int(deployment["id"])}/statuses')
        if any(s['state'] == 'success' for s in states):
            successful.append(deployment['sha'])
    def ancestor(a, b):
        require(all(re.fullmatch(r'[0-9a-f]{40,64}', x) for x in (a, b)), 'invalid deployment SHA')
        result = subprocess.run(['git', 'merge-base', '--is-ancestor', a, b], capture_output=True)
        require(result.returncode in (0, 1), 'deployment SHA not available in checked-out history')
        return result.returncode == 0
    return decision(current, main, successful, ancestor)
