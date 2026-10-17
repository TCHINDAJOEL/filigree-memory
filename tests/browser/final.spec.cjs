// Final integration regressions (UI): external monitor on a --no-capture server, declared actor labels, memory diagnostics.
// Synthetic data only. Every server has its own data directory, home and empty sources; the --no-capture server also runs
// with tripwires on every capture-source entry point, which append to a trap file instead of reading anything.
const fs = require('fs');
const net = require('net');
const path = require('path');
const {spawn, spawnSync} = require('child_process');
const {test, expect} = require('@playwright/test');

const repo = path.resolve(__dirname, '..', '..');
const work = path.join(repo, '.runtime', 'final-ui', `${Date.now()}-${process.pid}`);
fs.mkdirSync(work, {recursive: true});

const freePort = () => new Promise((resolve, reject) => {
  const probe = net.createServer();
  probe.once('error', reject);
  probe.listen(0, '127.0.0.1', () => { const {port} = probe.address(); probe.close(() => resolve(port)); });
});
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const isolatedEnv = base => {
  const home = path.join(base, 'home');
  for (const name of ['home', 'claude-config', 'codex-home', 'tap']) fs.mkdirSync(path.join(base, name), {recursive: true});
  return {...process.env, HOME: home, USERPROFILE: home, APPDATA: path.join(home, 'AppData'), LOCALAPPDATA: path.join(home, 'AppData'),
    CLOUDTAP_DB: path.join(base, 'tap', 'absent.sqlite3'), CLAUDE_CONFIG_DIR: path.join(base, 'claude-config'), CODEX_HOME: path.join(base, 'codex-home'), PYTHONUTF8: '1'};
};
const python = (code, args, env) => spawnSync('python', ['-I', '-c', code, repo, ...args], {cwd: repo, env, encoding: 'utf8'});

const SEED = `
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from filigree.store import Store
data, folder = Path(sys.argv[2]), Path(sys.argv[3])
folder.mkdir(parents=True, exist_ok=True)
store = Store(data)
project = store.create_project('Projet final', '', folder=folder)
entry = store.create_entry(project['id'], {'title': 'Choix déclaré', 'body': 'Corps', 'kind': 'decision', 'status': 'proposed', 'agent': 'Dr. Martin <b>vrai humain</b>', 'tags': [], 'sources': [], 'relations': []}, channel='http-ui')
if len(sys.argv) > 4:
    base = data / 'projects' / project['id'] / '.filigree'
    (base / 'entries' / '11111111-1111-4111-8111-111111111111.md').write_text('pas une connaissance', encoding='utf-8')
    (base / 'events').mkdir(exist_ok=True)
    (base / 'events' / '2026-01-01-corrompu.json').write_text('{', encoding='utf-8')
`;
const SERVER = `
import sys
sys.path.insert(0, sys.argv[1])
trap = sys.argv[4]
from unittest.mock import patch
def forbidden(*a, **k):
    with open(trap, 'a', encoding='utf-8') as out:
        out.write('source touched\\n')
    raise RuntimeError('capture source touched')
for target in ['filigree.capture.Capture.__init__', 'filigree.capture.Capture.scan_once', 'filigree.capture.tap_source.probe', 'filigree.capture.tap_source.resolve_db_path',
               'filigree.capture.native_index.default_roots', 'filigree.capture.native_index.NativeIndex', 'filigree.tap_source.probe']:
    patch(target, side_effect=forbidden).start()
from filigree.cli import main
main(['--data-dir', sys.argv[2], 'serve', '--port', sys.argv[3], '--no-capture'])
`;
const HOLDER = `
import sys, time, pathlib
sys.path.insert(0, sys.argv[1])
from filigree.capture import ProcessLock
d = pathlib.Path(sys.argv[2]); d.mkdir(exist_ok=True)
lock = ProcessLock(d / 'capture.lock'); assert lock.acquire(); print('held', flush=True)
end = time.time() + 90
while time.time() < end and not (d / 'stop').exists(): time.sleep(0.05)
lock.release()
`;

async function start(name, {corrupt = false, trap = false} = {}) {
  const base = path.join(work, name), data = path.join(base, 'data'), env = isolatedEnv(base);
  fs.mkdirSync(base, {recursive: true});
  const seeded = python(SEED, [data, path.join(base, 'folder'), ...(corrupt ? ['corrupt'] : [])], env);
  if (seeded.status !== 0) throw new Error(`seed failed: ${seeded.stderr}`);
  const port = await freePort(), trapFile = path.join(base, 'trap.log');
  const log = fs.openSync(path.join(base, 'server.log'), 'w');
  const child = trap
    ? spawn('python', ['-I', '-c', SERVER, repo, data, String(port), trapFile], {cwd: repo, env, stdio: ['ignore', log, log]})
    : spawn('python', ['-m', 'filigree', '--data-dir', data, 'serve', '--port', String(port), '--no-capture'], {cwd: repo, env, stdio: ['ignore', log, log]});
  const origin = `http://127.0.0.1:${port}`;
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch(origin)).ok) return {origin, child, data, env, trapFile}; } catch { /* not listening yet */ }
    await sleep(150);
  }
  child.kill();
  throw new Error(`server ${name} did not start`);
}

test.describe.configure({mode: 'serial', timeout: 90000});
const servers = [];
test.afterAll(() => { for (const server of servers) { server.child.kill(); server.holder?.kill(); } });

test('external monitor on the same data directory is shown honestly and can be asked to stop; controls stay unavailable', async ({page}) => {
  const server = await start('monitor', {trap: true});
  servers.push(server);
  server.holder = spawn('python', ['-I', '-c', HOLDER, repo, path.join(server.data, '.capture')], {cwd: repo, env: server.env, stdio: ['ignore', 'pipe', 'pipe']});
  await new Promise((resolve, reject) => { server.holder.stdout.once('data', resolve); server.holder.once('exit', () => reject(new Error('holder exited'))); });
  const posts = [];
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/api/capture')) posts.push(request.postDataJSON()); });
  await page.goto(server.origin + '/');
  await expect(page.locator('#main')).toHaveAttribute('aria-busy', 'false');
  await page.locator('[data-view="capture"]').click();
  await expect(page.locator('#capture-banner')).toContainText('moniteur externe');
  await expect(page.locator('#capture-pill')).toContainText('Moniteur externe actif');
  const controls = page.locator('#capture-controls');
  await expect(controls).toContainText('--no-capture');
  // Startup and configuration controls stay unavailable; only the cooperative stop is offered.
  await expect(controls.locator('button')).toHaveCount(1);
  await expect(controls.getByRole('button', {name: 'Arrêter le moniteur externe'})).toBeVisible();
  for (const name of ['Activer la capture', 'Désactiver la capture', 'Démarrer le moniteur', 'Suspendre']) await expect(page.getByRole('button', {name})).toHaveCount(0);
  await controls.getByRole('button', {name: 'Arrêter le moniteur externe'}).click();
  await expect(page.locator('#capture-banner')).not.toContainText('moniteur externe', {timeout: 15000});
  await expect(page.locator('#capture-controls button')).toHaveCount(0);
  expect(posts).toEqual([{action: 'stop'}]);
  await expect.poll(() => server.holder.exitCode, {timeout: 15000}).toBe(0); // the monitor stopped by itself, nobody killed it
  expect(fs.existsSync(server.trapFile)).toBe(false); // no capture source entry point was ever called
});

test('actor labels are shown as declared, not authenticated, with the server-set channel; hostile names stay inert', async ({page}) => {
  const server = await start('labels');
  servers.push(server);
  await page.goto(server.origin + '/');
  await expect(page.locator('#main')).toHaveAttribute('aria-busy', 'false');
  await page.locator('[data-view="entries"]').click();
  const row = page.locator('.knowledge-row').first();
  await expect(row).toContainText('Déclaré : Dr. Martin <b>vrai humain</b>');
  await expect(row.locator('b')).toHaveCount(0);
  await row.getByRole('button', {name: 'Choix déclaré'}).click();
  const detail = page.locator('#detail');
  await expect(detail).toContainText('Déclaré par Dr. Martin <b>vrai humain</b> (non authentifié)');
  await expect(detail).toContainText('Canal : interface locale');
  await expect(detail.locator('.detail-meta b')).toHaveCount(0);
  await page.keyboard.press('Escape');
  await page.locator('[data-view="timeline"]').click();
  await expect(page.locator('.timeline-full')).toContainText('canal : interface locale');
});

test('quarantined entry and event files are announced instead of silently omitted; a healthy memory shows nothing', async ({page}) => {
  const clean = await start('clean');
  servers.push(clean);
  await page.goto(clean.origin + '/');
  await expect(page.locator('#main')).toHaveAttribute('aria-busy', 'false');
  await expect(page.locator('.knowledge-row').first()).toBeVisible();
  await expect(page.locator('#diagnostics')).toBeEmpty();
  const broken = await start('broken', {corrupt: true});
  servers.push(broken);
  await page.goto(broken.origin + '/');
  await expect(page.locator('#main')).toHaveAttribute('aria-busy', 'false');
  const notice = page.locator('#diagnostics [role="alert"]');
  await expect(notice).toContainText('2 fichiers de mémoire illisibles');
  await expect(notice).toContainText('11111111-1111-4111-8111-111111111111.md');
  await expect(notice).toContainText('2026-01-01-corrompu.json');
  await expect(notice).toContainText('Rien n’a été modifié ni supprimé');
  const {token} = await (await fetch(broken.origin + '/api/bootstrap')).json();  // API reads need the local key
  const listed = await (await fetch(broken.origin + '/api/projects', {headers: {'X-Filigree-Token': token}})).json();
  expect(fs.readFileSync(path.join(broken.data, 'projects', listed[0].id, '.filigree', 'events', '2026-01-01-corrompu.json'), 'utf8')).toBe('{');
});
