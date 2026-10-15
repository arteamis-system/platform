import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const directory = dirname(fileURLToPath(import.meta.url));
const sourcePath = resolve(directory, 'node_modules/ungit/source/git-api.js');
const original = `  app.get(\`\${exports.pathPrefix}/diff/image\`, ensureAuthenticated, ensurePathExists, (req, res) => {
    res.type(path.extname(req.query.filename));
    if (req.query.version !== 'current') {
      gitPromise.binaryFileContent(req.query.path, req.query.filename, req.query.version, res);
    } else {
      res.sendFile(path.join(req.query.path, req.query.filename));
    }
  });`;

const patched = `  // Arteamis: a missing image in a parent commit is an expected preview failure.
  app.get(\`\${exports.pathPrefix}/diff/image\`, ensureAuthenticated, ensurePathExists, async (req, res) => {
    res.type(path.extname(req.query.filename));
    if (req.query.version === 'current') {
      res.sendFile(path.join(req.query.path, req.query.filename), (err) => {
        if (err && !res.headersSent) {
          res.status(err.statusCode || err.status || 500).end();
        } else if (err && !res.writableEnded) {
          res.destroy();
        }
      });
      return;
    }
    try {
      // Check before streaming, so absent revisions/files produce a real 404.
      await gitPromise(['cat-file', '-e', \`\${req.query.version}:\${req.query.filename}\`], req.query.path);
      await gitPromise.binaryFileContent(req.query.path, req.query.filename, req.query.version, res);
    } catch (err) {
      if (!res.headersSent) {
        res.status(404).end();
      } else if (!res.writableEnded) {
        res.destroy();
      }
    }
  });`;

const source = readFileSync(sourcePath, 'utf8');
if (source.includes(original)) {
  writeFileSync(sourcePath, source.replace(original, patched));
  console.log('Applied Ungit image preview fix.');
} else if (!source.includes(patched)) {
  throw new Error('Ungit image preview code changed; review the local patch before starting.');
}
