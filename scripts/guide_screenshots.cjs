// Regenerates the screenshots of docs/guide/ from the real workbench, with fictional data only.
//   node scripts/guide_screenshots.cjs
// It starts `filigree serve --no-capture` on a fresh data folder under .runtime/guide/, walks the interface like a
// user (demo project, review, views), seeds a synthetic activity journal through Filigree's own Python API and writes
// PNG files to docs/guide/images/. No agent data, network service or model is used.
const fs = require('fs');
const path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('@playwright/test');

const root = path.resolve(__dirname, '..');
const base = path.join(root, '.runtime', 'guide', new Date().toISOString().replace(/[-:.TZ]/g, ''));
const memory = path.join(base, 'memory');
const images = path.join(root, 'docs', 'guide', 'images');
const port = 7831;
fs.mkdirSync(path.join(memory, '.capture'), {recursive: true});
fs.mkdirSync(images, {recursive: true});
fs.mkdirSync(path.join(base, 'sources', 'claude'), {recursive: true});
fs.writeFileSync(path.join(memory, '.capture', 'capture.json'), JSON.stringify({tap: {enabled: false}, roots: {claude: path.join(base, 'sources', 'claude'), codex: path.join(base, 'sources', 'codex')}}));
const workFolder = path.join(require('os').tmpdir(), 'Projets', 'boutique-en-ligne');  // a readable path for the screenshots
fs.mkdirSync(workFolder, {recursive: true});

const python = (code, ...args) => execFileSync('python', ['-c', code, ...args], {env: {...process.env, PYTHONPATH: root}, encoding: 'utf8'});

const seedActivity = projectId => python(`
import json, os, sys
from datetime import datetime, timedelta, timezone
from filigree.activity import ActivityLog, journal_path
from filigree.distill import distill_project
from filigree.store import Store
store = Store(sys.argv[1]); pid = sys.argv[2]; folder = sys.argv[3]
now = datetime.now(timezone.utc)
t = lambda minutes: (now - timedelta(minutes=minutes)).isoformat(timespec="seconds")
log = ActivityLog(journal_path(store, pid))
log.add({"session_key": "claude:7f3a:9b21c4d0-old", "client": "claude", "model": "claude-sonnet", "entrypoint": "cli", "cwd": folder}, [
  {"event_id": "a1", "kind": "user_prompt", "ts_observed": t(95), "ts_source": t(95), "summary": "Ajoute un export CSV des commandes"},
  {"event_id": "a2", "kind": "file_change", "ts_observed": t(93), "ts_source": t(93), "summary": "Edit · export.py", "files": [os.path.join(folder, "export.py")]},
  {"event_id": "a3", "kind": "command", "ts_observed": t(92), "ts_source": t(92), "summary": "tests · python"},
  {"event_id": "a4", "kind": "test_result", "ts_observed": t(91), "ts_source": t(91), "summary": "réussi · python · 12 passed in 0.84s"},
  {"event_id": "a5", "kind": "commit", "ts_observed": t(90), "ts_source": t(90), "summary": "git commit"}])
log.add({"session_key": "claude:7f3a:4e88a1f2-now", "client": "claude", "model": "claude-haiku", "entrypoint": "cli", "cwd": folder}, [
  {"event_id": "b1", "kind": "user_prompt", "ts_observed": t(6), "ts_source": t(6), "summary": "Corrige le calcul de la TVA dans le panier"},
  {"event_id": "b2", "kind": "file_change", "ts_observed": t(5), "ts_source": t(5), "summary": "Edit · cart.py", "files": [os.path.join(folder, "cart.py")]},
  {"event_id": "b3", "kind": "error", "ts_observed": t(4), "ts_source": t(4), "summary": "AssertionError: 19.6 != 20.0 dans test_cart_total"}])
log.add({"session_key": "codex:51c0:thread-77ad", "client": "codex", "model": "gpt-5-codex", "cwd": folder}, [
  {"event_id": "c1", "kind": "user_prompt", "ts_observed": t(3), "ts_source": t(3), "summary": "Ajoute la remise fidélité au panier"},
  {"event_id": "c2", "kind": "file_change", "ts_observed": t(2), "ts_source": t(2), "summary": "apply_patch · cart.py", "files": [os.path.join(folder, "cart.py")]}])
print(distill_project(store, pid, {}, idle_minutes=10))
`, memory, projectId, workFolder);

(async () => {
  // A real agent (capture + observer), confined to empty synthetic sources: nothing of the machine is read.
  const isolated = {CLAUDE_CONFIG_DIR: path.join(base, 'sources', 'claude'), CODEX_HOME: path.join(base, 'sources', 'codex'), APPDATA: path.join(base, 'sources', 'roaming'), LOCALAPPDATA: path.join(base, 'sources', 'local'), CLOUDTAP_DB: path.join(base, 'absent.sqlite3')};
  const server = spawn('python', ['-m', 'filigree', '--data-dir', memory, 'agent', '--port', String(port)], {env: {...process.env, PYTHONPATH: root, ...isolated}});
  await new Promise((resolve, reject) => { server.stdout.on('data', d => String(d).includes('http://') && resolve()); server.on('exit', reject); setTimeout(() => reject(new Error('server timeout')), 15000); });
  const browser = await chromium.launch();
  const page = await browser.newPage({viewport: {width: 1440, height: 900}, deviceScaleFactor: 1});
  const shot = async (name, options = {}) => { await page.waitForTimeout(400); await page.screenshot({path: path.join(images, name), ...options}); console.log('✓', name); };
  try {
    await page.goto(`http://127.0.0.1:${port}/`);
    await page.getByRole('button', {name: 'Explorer la démonstration'}).waitFor();
    await shot('01-accueil.png');
    await page.getByRole('button', {name: 'Créer mon premier projet'}).click();
    await page.getByLabel('Nom du projet', {exact: true}).fill('Boutique en ligne');
    await page.getByLabel('Dossier du projet').fill(workFolder);
    await page.getByLabel('Intention du projet').fill('Garder les décisions techniques de la boutique et leurs raisons.');
    await shot('02-creer-projet.png');
    await page.getByRole('button', {name: 'Créer le projet', exact: true}).click();
    await page.locator('#project-name').filter({hasText: 'Boutique en ligne'}).waitFor();
    const shop = await page.evaluate(async () => { const {token} = await (await fetch('/api/bootstrap')).json(); return (await (await fetch('/api/projects', {headers: {'X-Filigree-Token': token}})).json()).find(p => p.name === 'Boutique en ligne').id; });
    seedActivity(shop);
    await page.locator('#new-project').waitFor();
    await page.evaluate(async () => { const {token} = await (await fetch('/api/bootstrap')).json(); const r = await fetch('/api/demo', {method: 'POST', headers: {'X-Filigree-Token': token, 'Content-Type': 'application/json'}, body: '{}'}); if (!r.ok) throw new Error('demo ' + r.status + ' ' + await r.text()); });
    const demo = await page.evaluate(async () => { const {token} = await (await fetch('/api/bootstrap')).json(); return (await (await fetch('/api/projects', {headers: {'X-Filigree-Token': token}})).json()).find(p => p.demo || /démonstration|demo/i.test(p.name)).id; });
    const open = async (id, view) => { await page.evaluate(id => localStorage.setItem('filigree.project', id), id); await page.goto(`http://127.0.0.1:${port}/#${view}`); await page.reload(); await page.locator('#view-name').waitFor(); await page.waitForTimeout(600); };
    await open(demo, 'overview');
    await shot('03-vue-ensemble.png');
    await open(demo, 'entries');
    await shot('04-connaissances.png');
    await page.locator('.knowledge-list [data-entry]').first().click();
    await page.locator('#modal[open], dialog[open]').first().waitFor();
    await shot('05-detail-connaissance.png');
    await page.keyboard.press('Escape');
    await open(demo, 'timeline');
    await shot('06-chronologie.png');
    await open(demo, 'graph');
    await page.waitForTimeout(800);
    await shot('07-graphe.png');
    await open(demo, 'handoff');
    await page.locator('.code-output').waitFor();
    await shot('08-reprise.png');
    await open(shop, 'activity');
    await page.locator('.activity-feed').waitFor();
    await page.setViewportSize({width: 1440, height: 1240});
    await page.waitForTimeout(300);
    await shot('09-activite.png');
    await page.setViewportSize({width: 1440, height: 900});
    await open(shop, 'entries');
    await shot('10-fiche-session.png');
    await page.locator('.knowledge-list [data-entry]').first().click();
    await page.locator('dialog[open]').first().waitFor();
    await shot('11-fiche-session-detail.png');
    await page.keyboard.press('Escape');
    await open(shop, 'capture');
    await page.locator('#capture-controls').waitFor();
    await page.waitForTimeout(800);
    await shot('12-capture.png');
    await open(shop, 'import');
    await shot('13-importer.png');
    await page.setViewportSize({width: 390, height: 844});
    await open(shop, 'activity');
    await page.locator('.activity-feed').waitFor();
    await shot('14-mobile-activite.png');
  } finally {
    await browser.close();
    server.kill();
  }
  console.log('images →', images, '· données →', base);
})().catch(error => { console.error(error); process.exit(1); });
