import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync, realpathSync } from 'node:fs';
import { resolve } from 'node:path';

function repositoryPath(candidate) {
  try {
    const directory = realpathSync(candidate);
    if (!existsSync(resolve(directory, '.git'))) return null;
    const top = execFileSync('git', ['-C', directory, 'rev-parse', '--show-toplevel'], {
      encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
    }).trim();
    return realpathSync(top) === directory ? directory : null;
  } catch {
    return null;
  }
}

export function discoverRepositories(root, explicit = []) {
  if (explicit.length) {
    return [...new Set(explicit.map((candidate) => {
      const repository = repositoryPath(resolve(candidate));
      if (!repository) throw new Error(`Not a Git checkout: ${candidate}`);
      return repository;
    }))].sort();
  }

  const directory = realpathSync(root);
  const single = repositoryPath(directory);
  if (single) return [single];

  return [...new Set(readdirSync(directory, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() || entry.isSymbolicLink())
    .map((entry) => repositoryPath(resolve(directory, entry.name)))
    .filter(Boolean))].sort();
}
