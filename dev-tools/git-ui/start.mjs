import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { discoverRepositories } from './repositories.mjs';

const directory = dirname(fileURLToPath(import.meta.url));

async function main() {
  const { values } = parseArgs({ options: {
    root: { type: 'string' },
    repo: { type: 'string', multiple: true },
    port: { type: 'string' },
    list: { type: 'boolean' },
    help: { type: 'boolean', short: 'h' },
  } });

  if (values.help) {
    console.log(`Usage: node dev-tools/git-ui/start.mjs [--root FOLDER] [--repo CHECKOUT ...] [--port PORT] [--list]

Default: discover Git checkouts beside platform and serve on port 8449.
--root accepts a folder of checkouts or a single checkout.
--repo may be repeated to select exact checkouts, including repos without remotes.
--list prints discovered paths without installing dependencies or starting a server.
Environment defaults: ARTEAMIS_GIT_UI_ROOT, ARTEAMIS_GIT_UI_PORT.`);
    return;
  }

  const [major, minor] = process.versions.node.split('.').map(Number);
  if (!(major >= 23 || (major === 22 && minor >= 12) || (major === 20 && minor >= 19))) {
    throw new Error('Ungit requires Node 20.19+, Node 22.12+, or Node 23+.');
  }
  const root = resolve(values.root || process.env.ARTEAMIS_GIT_UI_ROOT || resolve(directory, '../../..'));
  const repositories = discoverRepositories(root, values.repo || []);
  if (!repositories.length) {
    throw new Error(`No Git checkouts found in ${root}. Use --root or --repo to select repositories.`);
  }
  if (values.list) {
    console.log(JSON.stringify(repositories, null, 2));
    return;
  }

  const port = values.port || process.env.ARTEAMIS_GIT_UI_PORT || '8449';
  if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) {
    throw new Error('Port must be an integer from 1 to 65535.');
  }
  const url = `http://127.0.0.1:${port}`;
  let existing;
  try {
    existing = await fetch(`${url}/serverdata.js`, { signal: AbortSignal.timeout(1500) });
  } catch (error) {
    if (error.cause?.code !== 'ECONNREFUSED') {
      throw new Error(`Cannot use ${url}; another service may be listening. Choose --port PORT.`);
    }
  }
  if (existing) {
    const match = (await existing.text()).match(/^ungit\.config = (.+);$/m);
    if (!existing.ok || !match ||
        JSON.stringify(JSON.parse(match[1]).defaultRepositories) !== JSON.stringify(repositories)) {
      throw new Error(`Port ${port} is already in use with different repositories. Choose --port PORT.`);
    }
    console.log(`Arteamis Git UI already running: ${url} (${repositories.length} repositories)`);
    return;
  }

  const binary = resolve(directory, 'node_modules/ungit/bin/ungit');
  if (!existsSync(binary)) {
    const install = spawnSync(process.platform === 'win32' ? 'npm.cmd' : 'npm',
      ['ci', '--no-audit', '--no-fund'], {
        cwd: directory, stdio: 'inherit', shell: process.platform === 'win32',
      });
    if (install.error) throw install.error;
    if (install.status !== 0) throw new Error('Installing Ungit failed. Check Node/npm and registry access.');
  }

  await import('./patch-ungit.mjs');
  const runtime = resolve(directory, '.runtime');
  mkdirSync(runtime, { recursive: true });
  const config = resolve(runtime, `ungitrc-${port}.json`);
  writeFileSync(config, JSON.stringify({
    defaultRepositories: repositories,
    ungitBindIp: '127.0.0.1',
    launchBrowser: false,
    autoFetch: false,
    bugtracking: false,
    logRESTRequests: false,
    diffType: 'sidebysidediff',
    numberOfNodesPerLoad: 50,
  }, null, 2) + '\n');
  console.log(`Arteamis Git UI: ${repositories.length} repositories; ${url}`);

  const server = spawn(process.execPath, [binary, `--config=${config}`, `--port=${port}`,
    '--ungitBindIp=127.0.0.1', '--no-launchBrowser', '--no-autoFetch'], {
    cwd: directory, stdio: 'inherit',
  });
  for (const signal of ['SIGINT', 'SIGTERM']) {
    process.on(signal, () => server.kill(signal));
  }
  server.on('error', (error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
  server.on('exit', (code, signal) => {
    process.exitCode = code ?? (signal === 'SIGINT' ? 130 : 1);
  });
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
