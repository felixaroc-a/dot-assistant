const { rebuild } = require('@electron/rebuild');
const path = require('path');

const buildPath = path.resolve(__dirname, '..');

console.log('buildPath:', buildPath);

rebuild({
  buildPath: buildPath,
  electronVersion: '40.4.0',
  onlyModules: ['better-sqlite3'],
}).then(() => {
  console.log('REBUILD OK');
}).catch(e => {
  console.error('REBUILD FAILED:', e.message);
  process.exit(1);
});
