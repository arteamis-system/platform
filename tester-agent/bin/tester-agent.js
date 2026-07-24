#!/usr/bin/env node
// Thin launcher for the compiled CLI.
import { main } from '../dist/cli.js';

main()
  .then((code) => {
    process.exitCode = code;
  })
  .catch((err) => {
    console.error(err instanceof Error ? err.stack : String(err));
    process.exitCode = 1;
  });
