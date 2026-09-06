import { cpSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const root = dirname(require.resolve('cesium/package.json'));
mkdirSync('public/cesium', { recursive: true });
for (const folder of ['Assets', 'Workers', 'ThirdParty', 'Widgets'])
  cpSync(join(root, 'Build/Cesium', folder), join('public/cesium', folder), {
    recursive: true,
  });
