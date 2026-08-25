import {
  cpSync,
  existsSync,
  rmSync,
} from 'node:fs';
import { dirname, resolve } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const standaloneRoot = resolve(frontendRoot, '.next', 'standalone');
const standaloneServer = resolve(standaloneRoot, 'server.js');

function copyRuntimeDirectory(source, destination) {
  if (!existsSync(source)) {
    throw new Error(`Standalone runtime asset directory is missing: ${source}`);
  }
  rmSync(destination, { force: true, recursive: true });
  cpSync(source, destination, { recursive: true });
}

if (!existsSync(standaloneServer)) {
  throw new Error('Standalone Next.js server is missing; run `npm run build` first.');
}

// Next's standalone trace intentionally excludes public and generated static
// assets. Mirror the production Docker image layout before starting the E2E
// server so the browser suite exercises the supported deployment artifact.
copyRuntimeDirectory(
  resolve(frontendRoot, 'public'),
  resolve(standaloneRoot, 'public'),
);
copyRuntimeDirectory(
  resolve(frontendRoot, '.next', 'static'),
  resolve(standaloneRoot, '.next', 'static'),
);

await import(pathToFileURL(standaloneServer).href);
