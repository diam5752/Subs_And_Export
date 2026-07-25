'use strict';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { readFileSync, writeFileSync } = require('node:fs');

const entrypoint = require.resolve('brace-expansion');
const marker = '// gsubs: patched v5 legacy callable export';
const source = readFileSync(entrypoint, 'utf8');

if (source.includes(marker)) {
  process.exit(0);
}

if (!source.includes('exports.expand = expand;')) {
  throw new Error(`Unexpected brace-expansion CommonJS entrypoint: ${entrypoint}`);
}

const compatibilityExport = `

${marker}
const legacyCompatibleExpand = module.exports.expand;
Object.assign(legacyCompatibleExpand, module.exports);
module.exports = legacyCompatibleExpand;
`;

writeFileSync(entrypoint, source + compatibilityExport, 'utf8');
