# Local Git browser

Ungit shows commit graphs, branch refs, commit and working-tree diffs, and
optional Git operations for existing local checkouts. The launcher and pinned
dependencies live in platform; no GOL checkout or application setup is needed.

## Setup on another device

Install Git, npm, and Node 20.19+, Node 22.12+, or Node 23+.
Clone platform and whichever other repositories you want to browse into the
same parent folder, for example:

```text
arteamis/
  platform/
  backend/
  web/
  desktop/
  landing/
  product/
  .github/
```

Only platform is required. A partial workspace works, and folder names and
remote URLs do not need to match this example.

From the platform checkout:

```sh
./git-ui.sh
```

The cross-platform equivalent, including Windows, is:

```sh
node dev-tools/git-ui/start.mjs
```

The first start runs `npm ci` using the committed lockfile. Later starts reuse
the installed dependencies. Open http://127.0.0.1:8449. Port 8449 lets this run
alongside GOL's Git browser on port 8448. The server binds to 127.0.0.1 and stops
with Ctrl-C. Running the same command again reuses a matching running instance.
Dependencies and generated settings are gitignored.

The default search finds Git checkouts immediately beside platform, including
`.github`, linked worktrees and repositories without remotes. It does not
recurse into nested scratch folders. Select another layout with:

```sh
./git-ui.sh --root /path/to/workspace
./git-ui.sh --root /path/to/single-checkout
./git-ui.sh --repo /path/to/backend --repo /elsewhere/web
./git-ui.sh --port 8450
./git-ui.sh --list
```

The same arguments work with the Node command. Quote paths containing spaces.
`ARTEAMIS_GIT_UI_ROOT` and `ARTEAMIS_GIT_UI_PORT` override the defaults.
`--list` prints selected paths without installing anything or starting a server;
`--help` shows the options. After cloning another sibling repository, stop and
restart the server to refresh the list.

The home page lists the selected repositories. Click a repository to see its
graph, then a commit and file to inspect its diff. Open repository links in
separate tabs to keep multiple graphs visible. Automatic fetch is disabled;
use Fetch when you want to update remote branch refs.

## Checks

Run from platform:

```sh
npm ci --prefix dev-tools/git-ui --no-audit --no-fund
node --test dev-tools/git-ui/*.test.mjs
python3 dev-tools/git-ui/test-image-previews.py
./git-ui.sh --list
```

Each start reapplies a local fix to Ungit 1.5.30's image preview route. Missing
images in parent commits return HTTP 404 without stopping the server. The
HTTP regression checks cover added, removed, renamed and initial-commit images,
and verify that commit history still works after a failed preview. Discovery
checks use temporary repositories and linked worktrees. These checks also run
in `.github/workflows/git-ui-tests.yml`.
