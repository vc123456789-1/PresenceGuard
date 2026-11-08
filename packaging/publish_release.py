"""Publish reviewed Windows artifacts as a GitHub prerelease.

Dry run by default. The Git credential is obtained from Git Credential Manager
and remains in memory. No PIN, camera data, settings or local history is read.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError

PROJECT = Path(__file__).resolve().parents[1]
REPOSITORY = 'vc123456789-1/PresenceGuard'
OWNER = 'vc123456789-1'
API = 'https://api.github.com'
FILES = ('PresenceGuard-Setup-x64.exe', 'PresenceGuard-Portable-x64.zip')


def call(url, token, method='GET', data=None, content_type=None):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'PresenceGuard-release',
               'X-GitHub-Api-Version': '2022-11-28', 'Authorization': 'Bearer ' + token}
    if content_type:
        headers['Content-Type'] = content_type
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=240) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError('GitHub request failed with HTTP %s.' % exc.code) from None


def credential():
    env = {**os.environ, 'GCM_INTERACTIVE': 'never', 'GIT_TERMINAL_PROMPT': '0'}
    result = subprocess.run(['git', 'credential', 'fill'],
                            input='protocol=https\nhost=github.com\nusername=' + OWNER + '\n\n',
                            text=True, capture_output=True, env=env, timeout=15, check=True)
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if values.get('username') != OWNER or not values.get('password'):
        raise RuntimeError('A credential for the requested account is unavailable.')
    return values['password']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True)
    parser.add_argument('--target-sha', required=True)
    parser.add_argument('--publish', action='store_true', help='Create and publish the prerelease')
    args = parser.parse_args()
    if not args.tag or not args.target_sha or not all(c in '0123456789abcdef' for c in args.target_sha) or len(args.target_sha) != 40:
        parser.error('Use a valid full commit SHA and tag.')
    files = [PROJECT / 'release' / name for name in FILES]
    for path in files:
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError('Missing release artifact: ' + path.name)
        print(path.name, path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
    token = credential()
    account = call(API + '/user', token)
    if account.get('login', '').casefold() != OWNER.casefold():
        raise RuntimeError('The authenticated GitHub account is not the requested account.')
    branch = call(API + '/repos/' + REPOSITORY + '/commits/main', token)
    if branch.get('sha') != args.target_sha:
        raise RuntimeError('GitHub main does not match the reviewed source commit.')
    existing = call(API + '/repos/' + REPOSITORY + '/releases', token)
    if any(item['tag_name'] == args.tag for item in existing):
        raise RuntimeError('That release tag already exists. Inspect it before continuing.')
    print('Account, repository and source commit verified.')
    if not args.publish:
        print('Dry run only. No release was created.')
        return
    body = ('Windows x64 review build. The application starts in test mode. '
            'Real locking requires in-app confirmation and remains experimental. '
            'Face matching and photo protection have not been independently validated; '
            'the installer has not been tested on a clean Windows machine without Python. '
            'The photo challenge is not a proven defense against photos or video. '
            'See the README and test report for details.')
    release = call(API + '/repos/' + REPOSITORY + '/releases', token, 'POST',
                   json.dumps({'tag_name': args.tag, 'target_commitish': args.target_sha,
                               'name': 'PresenceGuard ' + args.tag + ' (preview)',
                               'body': body, 'draft': True, 'prerelease': True}).encode(),
                   'application/json')
    release_id = release['id']
    upload_url = release['upload_url'].split('{', 1)[0]
    print('Draft created:', release_id)
    for path in files:
        uploaded = call(upload_url + '?name=' + quote(path.name), token, 'POST',
                        path.read_bytes(), 'application/octet-stream')
        if uploaded.get('size') != path.stat().st_size or uploaded.get('state') != 'uploaded':
            raise RuntimeError('Upload verification failed for ' + path.name + '. Draft remains unpublished.')
        print('Uploaded:', path.name, uploaded['size'])
    published = call(API + '/repos/' + REPOSITORY + '/releases/' + str(release_id), token,
                     'PATCH', b'{"draft":false}', 'application/json')
    if published.get('draft') or not published.get('prerelease'):
        raise RuntimeError('Could not verify publication state.')
    print('Published prerelease:', published['html_url'])


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print('Release not completed:', str(exc))
        raise SystemExit(1)
