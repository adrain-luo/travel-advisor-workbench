"""Fetch private release assets using existing Git authentication; never log tokens."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request


class NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected and urllib.parse.urlparse(newurl).netloc != urllib.parse.urlparse(req.full_url).netloc:
            redirected.remove_header('Authorization')
        if redirected and urllib.parse.urlparse(newurl).scheme != 'https':
            raise ValueError('Non-HTTPS redirect refused')
        return redirected


def credential():
    value = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if value:
        return value
    env = {**os.environ, 'GCM_INTERACTIVE': 'never', 'GIT_TERMINAL_PROMPT': '0'}
    result = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
                            text=True, capture_output=True, env=env, timeout=30)
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if not values.get('password'):
        raise RuntimeError('Authenticate Git for github.com with Git Credential Manager, or run gh auth login and gh auth setup-git. Do not paste a token into chat.')
    return values['password']


def request(url, token, *, accept='application/vnd.github+json'):
    if urllib.parse.urlparse(url).netloc != 'api.github.com':
        raise ValueError('Only the GitHub API origin may receive credentials')
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token, 'Accept': accept,
                                             'User-Agent': 'travel-advisor-workbench-release',
                                             'X-GitHub-Api-Version': '2022-11-28'})
    return urllib.request.build_opener(NoCredentialRedirect()).open(req, timeout=120)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repo):
        parser.error('Expected owner/repository')
    token = credential()
    base = 'https://api.github.com/repos/' + args.repo
    with request(base, token) as response:
        repo = json.load(response)
    if repo.get('private') is not True:
        raise RuntimeError('Expected a private repository')
    with request(base + '/releases/tags/' + urllib.parse.quote(args.tag, safe=''), token) as response:
        release = json.load(response)
    if release['tag_name'] != args.tag or release.get('draft'):
        raise RuntimeError('Release is not published under the requested tag')
    args.output.mkdir(parents=True, exist_ok=True)
    downloaded = []
    for asset in release['assets']:
        name = asset['name']
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in {'.', '..'}:
            raise ValueError('Unsafe asset name')
        target = args.output / name
        temporary = target.with_suffix(target.suffix + '.partial')
        digest = hashlib.sha256()
        size = 0
        with request(asset['url'], token, accept='application/octet-stream') as response, temporary.open('wb') as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        if size != asset['size'] or (asset.get('digest') and asset['digest'] != 'sha256:' + digest.hexdigest()):
            temporary.unlink(missing_ok=True)
            raise ValueError('Asset size or GitHub digest mismatch: ' + name)
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest.hexdigest():
            temporary.unlink(missing_ok=True)
            raise ValueError('Refusing to overwrite a different asset: ' + name)
        temporary.replace(target)
        downloaded.append({'name': name, 'size': size, 'sha256': digest.hexdigest()})
    checksums = args.output / 'SHA256SUMS.txt'
    if not checksums.is_file():
        raise ValueError('Release lacks SHA256SUMS.txt')
    listed = set()
    for line in checksums.read_text(encoding='utf-8').splitlines():
        expected, name = line.split('  ', 1)
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
            raise ValueError('Unsafe checksum path')
        if hashlib.sha256((args.output / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Release checksum mismatch: ' + name)
        listed.add(name)
    if {x['name'] for x in downloaded} - {'SHA256SUMS.txt'} != listed:
        raise ValueError('Checksum inventory does not cover every release asset')
    print(json.dumps({'repository': repo['html_url'], 'private': True, 'tag': args.tag,
                      'release': release['html_url'], 'assets': downloaded}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as exc:
        raise SystemExit('GitHub API returned HTTP ' + str(exc.code) + '; verify repository access and tag.') from None
