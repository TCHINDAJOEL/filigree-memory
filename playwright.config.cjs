const fs = require('fs');
const path = require('path');
const { defineConfig } = require('@playwright/test');
// Every run gets its own fresh synthetic tree; earlier runs are left untouched (nothing is deleted).
const runId = `${new Date().toISOString().replace(/[-:.TZ]/g, '')}-${process.pid}`;
const base = path.resolve('.runtime', 'browser-runs', runId);
// Fixture project folders are real directories outside the memory root.
const projects = path.join(base, 'projects');
fs.mkdirSync(projects, {recursive: true});
process.env.FILIGREE_BROWSER_FOLDERS = projects;
// The browser server never captures and never looks at a real claude-tap database.
const absentTap = path.join(base, 'absent-tap', 'traces.sqlite3');
// Defense in depth: an accidental capture start can only read these synthetic roots.
const isolatedRoots = path.join(base, 'sources');
for (const name of ['claude', 'codex']) fs.mkdirSync(path.join(isolatedRoots, name), {recursive: true});
const memory = path.join(base, 'memory');
fs.mkdirSync(path.join(memory, '.capture'), {recursive: true});
fs.writeFileSync(path.join(memory, '.capture', 'capture.json'), JSON.stringify({
  tap: {enabled: true, db: absentTap},
  roots: {claude: path.join(isolatedRoots, 'claude'), codex: path.join(isolatedRoots, 'codex')}
}));
module.exports = defineConfig({
  testDir: './tests/browser',
  workers: 1,
  retries: 0,
  use: {baseURL: 'http://127.0.0.1:7821', browserName: 'chromium', viewport: {width: 1440, height: 1000}, trace: 'retain-on-failure'},
  webServer: {command: `python -m filigree --data-dir "${memory}" serve --port 7821 --no-capture`, env: {...process.env, CLOUDTAP_DB: absentTap}, url: 'http://127.0.0.1:7821', reuseExistingServer: false, timeout: 15000}
});
