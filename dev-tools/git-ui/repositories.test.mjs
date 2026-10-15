import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, test } from 'node:test';
import { discoverRepositories } from './repositories.mjs';

const temporary = [];
function workspace() {
  const path = realpathSync(mkdtempSync(join(tmpdir(), 'arteamis-git-ui-discovery-')));
  temporary.push(path);
  return path;
}
function git(path, ...args) {
  return execFileSync('git', ['-C', path, ...args], {
    encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
  }).trim();
}
function checkout(root, name, remote) {
  const path = join(root, name);
  mkdirSync(path);
  git(path, 'init', '--quiet');
  if (remote) git(path, 'remote', 'add', 'origin', remote);
  return path;
}
afterEach(() => {
  for (const directory of temporary.splice(0)) rmSync(directory, { recursive: true, force: true });
});

test('discovers available sibling checkouts regardless of folder name or remote', () => {
  const root = workspace();
  const backend = checkout(root, 'renamed-backend', 'https://github.com/arteamis-system/backend.git');
  assert.deepEqual(discoverRepositories(root), [backend]);
  const platform = checkout(root, 'platform', 'git@github.com:arteamis-system/platform.git');
  const profile = checkout(root, '.github', 'https://github.com/arteamis-system/.github.git');
  const local = checkout(root, 'local-without-remote');
  const scratch = join(root, '.local');
  mkdirSync(scratch);
  checkout(scratch, 'nested-checkout');
  writeFileSync(join(root, 'notes.txt'), 'not a repository\n');
  assert.deepEqual(discoverRepositories(root), [backend, platform, profile, local].sort());
});

test('accepts a single checkout or explicit checkouts, and rejects invalid selections', () => {
  const root = workspace();
  const local = checkout(root, 'local');
  assert.deepEqual(discoverRepositories(local), [local]);
  assert.deepEqual(discoverRepositories(root, [local, local]), [local]);
  assert.throws(() => discoverRepositories(root, [join(root, 'absent')]), /Not a Git checkout/);
  const subdirectory = join(local, 'subdirectory');
  mkdirSync(subdirectory);
  assert.throws(() => discoverRepositories(root, [subdirectory]), /Not a Git checkout/);
});

test('discovers linked worktrees whose .git is a file', () => {
  const root = workspace();
  const backend = checkout(root, 'backend');
  writeFileSync(join(backend, 'README.md'), 'fixture\n');
  git(backend, 'add', 'README.md');
  git(backend, '-c', 'user.name=Arteamis test', '-c', 'user.email=test@example.invalid',
    '-c', 'commit.gpgsign=false', 'commit', '--quiet', '--no-verify', '-m', 'Fixture');
  const worktree = join(root, 'backend-worktree');
  git(backend, 'worktree', 'add', '--quiet', '--detach', worktree, 'HEAD');
  assert.deepEqual(discoverRepositories(root), [backend, worktree].sort());
});

test('deduplicates symlinked repositories and ignores broken links and empty folders', () => {
  const root = workspace();
  assert.deepEqual(discoverRepositories(root), []);
  const backend = checkout(root, 'backend');
  symlinkSync(backend, join(root, 'backend-alias'), 'junction');
  symlinkSync(join(root, 'absent'), join(root, 'broken-link'), 'junction');
  assert.deepEqual(discoverRepositories(root), [backend]);
});
