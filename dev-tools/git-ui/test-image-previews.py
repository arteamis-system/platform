"""Exercise real HTTP image previews against a disposable Git repository."""

import base64
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


directory = Path(__file__).resolve().parent
png = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aFfoAAAAASUVORK5CYII='
)
subprocess.run(['node', str(directory / 'patch-ungit.mjs')], check=True)

with tempfile.TemporaryDirectory(prefix='arteamis-ungit-image-test-') as temporary:
    repo = Path(temporary) / 'repo'
    repo.mkdir()

    def git(*arguments):
        return subprocess.check_output(
            ['git', '-C', str(repo), *arguments], stderr=subprocess.STDOUT, text=True
        ).strip()

    def commit(message):
        git('add', '-A')
        git('-c', 'user.name=Arteamis test', '-c', 'user.email=test@example.invalid',
            '-c', 'commit.gpgsign=false', 'commit', '--quiet', '--no-verify', '-m', message)
        return git('rev-parse', 'HEAD')

    git('init', '--quiet')
    (repo / 'initial.png').write_bytes(png)
    initial = commit('Initial image')
    filename = 'added & space.png'
    (repo / filename).write_bytes(png)
    added = commit('Add image with special characters')
    renamed_filename = 'renamed.png'
    (repo / filename).rename(repo / renamed_filename)
    renamed = commit('Rename image')
    (repo / renamed_filename).unlink()
    removed = commit('Remove image')

    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    base = f'http://127.0.0.1:{port}'

    def request(route, **query):
        url = base + route
        if query:
            url += '?' + urllib.parse.urlencode(query)
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    with (Path(temporary) / 'server.log').open('w+') as log:
        process = subprocess.Popen([
            shutil.which('node'), str(directory / 'node_modules/ungit/bin/ungit'),
            '--cliconfigonly', f'--port={port}', '--no-launchBrowser', '--no-autoFetch',
        ], stdout=log, stderr=log)
        try:
            for attempt in range(150):
                try:
                    assert request('/api/ping')[0] == 200
                    break
                except (urllib.error.URLError, TimeoutError):
                    if process.poll() is not None:
                        raise RuntimeError('Ungit exited before becoming ready')
                    time.sleep(.1)
            else:
                raise TimeoutError('Ungit did not become ready')

            cases = [
                ('initial image', 'initial.png', initial, 200),
                ('initial image has no parent', 'initial.png', initial + '^', 404),
                ('added image', filename, added, 200),
                ('added image missing in parent', filename, added + '^', 404),
                ('renamed image old path', filename, renamed + '^', 200),
                ('renamed image new path', renamed_filename, renamed, 200),
                ('removed image old version', renamed_filename, removed + '^', 200),
                ('removed image new version', renamed_filename, removed, 404),
                ('current image', 'initial.png', 'current', 200),
                ('missing current image', renamed_filename, 'current', 404),
                ('invalid revision', 'initial.png', 'not-a-revision', 404),
            ]
            for label, image_file, version, expected_status in cases:
                status, body = request('/api/diff/image', path=str(repo),
                                       filename=image_file, version=version)
                assert status == expected_status, (label, status, expected_status)
                if status == 200:
                    assert body == png, (label, 'binary content changed')
                assert request('/api/ping')[0] == 200, label
                print('PASS:', label, flush=True)

            status, body = request('/api/gitlog', path=str(repo), limit=10)
            assert status == 200 and len(json.loads(body)['nodes']) == 4
            time.sleep(.2)
            assert request('/api/ping')[0] == 200
            log.flush()
            log.seek(0)
            assert 'UnhandledPromiseRejection' not in log.read()
            print('PASS: commit history still works after image preview failures')
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
