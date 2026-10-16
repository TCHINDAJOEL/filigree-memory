// Regression tests for the independent verification of 2026-10-16 (UI findings D-1..D-7 and the UI P3 items).
// Every server started here has its own empty data directory and explicit, empty, synthetic capture sources
// (claude-tap database, Claude and Codex roots, home): nothing of the real machine can be read, even if --no-capture misbehaves.
const fs = require('fs');
const net = require('net');
const path = require('path');
const {spawn, spawnSync} = require('child_process');
const {test, expect} = require('@playwright/test');

const repo = path.resolve(__dirname, '..', '..');
const work = path.join(repo, '.runtime', 'remediation-ui', `${Date.now()}`);
const shots = path.join(repo, '.runtime', 'remediation-ui', 'shots');
fs.mkdirSync(shots, {recursive: true});

const freePort = () => new Promise((resolve, reject) => {
  const probe = net.createServer();
  probe.once('error', reject);
  probe.listen(0, '127.0.0.1', () => { const {port} = probe.address(); probe.close(() => resolve(port)); });
});
const isolatedEnv = base => {
  const home = path.join(base, 'home'), claude = path.join(base, 'claude-config'), codex = path.join(base, 'codex-home'), tap = path.join(base, 'tap');
  for (const folder of [home, claude, codex, tap]) fs.mkdirSync(folder, {recursive: true});
  return {...process.env, HOME: home, USERPROFILE: home, APPDATA: path.join(home, 'AppData'), LOCALAPPDATA: path.join(home, 'AppData'), XDG_DATA_HOME: path.join(base, 'xdg'),
    CLOUDTAP_DB: path.join(tap, 'absent.sqlite3'), CLAUDE_CONFIG_DIR: claude, CODEX_HOME: codex, FILIGREE_DATA_DIR: path.join(base, 'data'), PYTHONUTF8: '1'};
};
async function startServer(name, seed) {
  const base = path.join(work, name), data = path.join(base, 'data'), folders = path.join(base, 'folders');
  fs.mkdirSync(folders, {recursive: true});
  const env = isolatedEnv(base);
  if (seed) {
    const done = spawnSync('python', ['-I', '-c', seed.code, data, folders, repo], {cwd: repo, env, encoding: 'utf8'});
    if (done.status !== 0) throw new Error(`seed failed: ${done.stderr}`);
  }
  const port = await freePort();
  const log = fs.openSync(path.join(base, 'server.log'), 'w');
  const child = spawn('python', ['-m', 'filigree', '--data-dir', data, 'serve', '--port', String(port), '--no-capture'], {cwd: repo, env, stdio: ['ignore', log, log]});
  const origin = `http://127.0.0.1:${port}`;
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch(origin)).ok) return {origin, child, folders}; } catch { /* not listening yet */ }
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  child.kill();
  throw new Error(`server ${name} did not start`);
}

// Entries shaped exactly like automatic capture stores them (see capture.py): tap and native-transcript proposals.
const seedCode = `
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[3])
from filigree.store import Store
data, folders = Path(sys.argv[1]), Path(sys.argv[2])
folder = folders / 'projet-capture'
folder.mkdir()
store = Store(data)
project = store.create_project('Projet capturé', '', folder=folder)
def provenance(collector, **more):
    base = {'collector': collector, 'native_id': 'nat-1abcdef', 'link': 'native', 'cwd': str(folder), 'claim': 'identifiants déclaratifs, non authentifiés'}
    base.update(more)
    return base
tap = {'title': 'Utilisateur · Quelle base choisir ?', 'body': 'Quelle base choisir ? <img src=x onerror="window.pwned=1">', 'agent': 'Humain via Claude Code', 'episode': 'nat-1abcdef', 'timestamp': '2026-10-16T10:00:00+00:00',
  'sources': [{'label': 'claude-tap · claude · abcd1234 #1', 'uri': 'tap:abcd1234-0000:1:u-0', 'excerpt': 'Quelle base choisir ?'}],
  'tags': ['capture', 'claude-tap'], 'provenance': provenance('claude-tap', tap_db_key='k', tap_session_id='abcd1234-0000', record_index=1, payload_sha256='00')}
native = {'title': 'Claude Code · Je choisis SQLite', 'body': 'Je choisis SQLite pour sa simplicité.', 'agent': 'Claude Code', 'episode': 'nat-1abcdef', 'timestamp': '2026-10-16T10:01:00+00:00',
  'sources': [{'label': 'transcription native claude · nat-1abc', 'uri': 'native:claude:nat-1abcdef:1:2', 'excerpt': 'Je choisis SQLite pour sa simplicité.'}],
  'tags': ['capture', 'repli-natif', 'claude-code'], 'provenance': provenance('native-fallback', native_source='claude', native_file='session.jsonl')}
store.import_events(project['id'], [tap, native], 'claude-tap', internal=True)
`;

let main;
test.describe.configure({mode: 'serial', timeout: 90000});
test.beforeAll(async () => { test.setTimeout(60000); main = await startServer('main', {code: seedCode}); });
test.afterAll(() => { if (main?.child) main.child.kill(); });

let counter = 0;
const makeFolder = (server, label) => { const folder = path.join(server.folders, `${label}-${++counter}`); fs.mkdirSync(folder, {recursive: true}); return folder; };
const call = (page, method, url, body) => page.evaluate(async ({method, url, body}) => {
  const {token} = await (await fetch('/api/bootstrap')).json();
  const response = await fetch(url, {method, headers: {'Content-Type': 'application/json', 'X-Filigree-Token': token}, body: body ? JSON.stringify(body) : undefined});
  return {status: response.status, body: await response.json()};
}, {method, url, body});
async function open(page, server = main) {
  await page.goto(server.origin + '/');
  await expect(page.locator('#main')).toHaveAttribute('aria-busy', 'false');
}
const newProject = async (page, name, server = main) => (await call(page, 'POST', '/api/projects', {name, folder: makeFolder(server, 'p'), description: ''})).body;
const newEntry = async (page, project, title, extra = {}) => (await call(page, 'POST', `/api/projects/${project.id}/entries`, {title, body: `Corps de ${title}`, kind: 'decision', status: 'proposed', agent: 'Humain', episode: '', tags: [], sources: [], relations: [], ...extra})).body;
const patch = async (page, project, entry, changes) => (await call(page, 'PATCH', `/api/projects/${project.id}/entries/${entry.id}`, {revision: entry.revision, ...changes})).body;
const accept = (page, project, entry) => patch(page, project, entry, {status: 'accepted'});
const choose = async (page, project) => { await page.getByLabel('Projet actif').selectOption(project.id); await expect(page.locator('#project-name')).toHaveText(project.name); };
const watch = page => {
  const problems = [];
  page.on('pageerror', error => problems.push(`pageerror: ${error.message}`));
  page.on('console', message => { if (['error', 'warning'].includes(message.type()) && !/Failed to load resource/.test(message.text())) problems.push(`console.${message.type()}: ${message.text()}`); });
  return problems;
};
const overlaps = (page, selectors) => page.evaluate(selectors => {
  const items = selectors.flatMap(selector => [...document.querySelectorAll(selector)].map(element => ({selector, element}))).filter(({element}) => {
    const rect = element.getBoundingClientRect(), style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  });
  const found = [];
  for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) {
    const a = items[i].element, b = items[j].element;
    if (a.contains(b) || b.contains(a)) continue;
    const r = a.getBoundingClientRect(), s = b.getBoundingClientRect();
    if (Math.min(r.right, s.right) - Math.max(r.left, s.left) > 1 && Math.min(r.bottom, s.bottom) - Math.max(r.top, s.top) > 1) found.push(`${items[i].selector} × ${items[j].selector}`);
  }
  return found;
}, selectors);

test('D-1: an open detail follows the stored entry and shows incoming relations', async ({page}) => {
  const problems = watch(page);
  await open(page);
  const project = await newProject(page, `Remplacement ${Date.now()}`);
  const old = await accept(page, project, await newEntry(page, project, 'Choisir Postgres'));
  const next = await accept(page, project, await newEntry(page, project, 'Choisir SQLite'));
  await page.reload();
  await choose(page, project);
  await page.locator('[data-view="entries"]').click();
  await page.getByRole('button', {name: 'Choisir Postgres', exact: true}).click();
  await expect(page.locator('#detail .detail-top .status')).toHaveText('Acceptée');
  await expect(page.locator('#detail')).toContainText('Cette connaissance n’est pas encore reliée');
  // Another actor (here the API) replaces it while the sheet is open: no reload, no re-opening.
  await patch(page, project, next, {relations: [{target: old.id, type: 'supersedes'}]});
  await expect(page.locator('#detail .detail-top .status')).toHaveText('Remplacée', {timeout: 15000});
  const incoming = page.locator('#detail .relation-row.incoming');
  await expect(incoming).toContainText('Choisir SQLite');
  await expect(incoming).toContainText('est remplacée par cette connaissance');
  // Following the link shows the outgoing side.
  await incoming.getByRole('button', {name: 'Choisir SQLite'}).click();
  await expect(page.locator('#detail .relation-row').first()).toContainText('remplace');
  expect(problems).toEqual([]);
});

test('D-1: replacing through the interface leaves a fresh, linked sheet behind', async ({page}) => {
  await open(page);
  const project = await newProject(page, `Remplacer ${Date.now()}`);
  await accept(page, project, await newEntry(page, project, 'Ancienne méthode'));
  await page.reload();
  await choose(page, project);
  await page.locator('[data-view="entries"]').click();
  await page.getByRole('button', {name: 'Ancienne méthode', exact: true}).click();
  await page.getByRole('button', {name: 'Remplacer', exact: true}).click();
  // The closed sheet no longer keeps stale content in the page.
  await expect(page.locator('#detail-content')).toBeEmpty();
  await page.getByLabel('Titre', {exact: true}).fill('Nouvelle méthode');
  await page.getByLabel('Contenu et raisons').fill('Elle remplace l’ancienne.');
  await page.getByRole('button', {name: 'Ajouter la connaissance', exact: true}).click();
  await expect(page.locator('#toast')).toContainText('Remplacement enregistré');
  await page.getByRole('button', {name: 'Ancienne méthode', exact: true}).click();
  await expect(page.locator('#detail .detail-top .status')).toHaveText('Remplacée');
  await expect(page.locator('#detail .relation-row.incoming')).toContainText('Nouvelle méthode');
});

test('D-1: only an accepted entry offers to be replaced, and the sheet says why', async ({page}) => {
  await open(page);
  const project = await newProject(page, `Remplaçable ${Date.now()}`);
  await newEntry(page, project, 'Simple proposition');
  await page.reload();
  await choose(page, project);
  await page.locator('[data-view="entries"]').click();
  await page.getByRole('button', {name: 'Simple proposition', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Remplacer', exact: true})).toHaveCount(0);
  await expect(page.locator('#detail')).toContainText('Seule une connaissance acceptée peut être remplacée');
});

test('D-2: an edit conflict is French, keeps the draft and offers the current version', async ({browser}) => {
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  const page = await context.newPage();
  await open(page);
  const project = await newProject(page, `Conflit ${Date.now()}`);
  const entry = await newEntry(page, project, 'Titre initial', {kind: 'observation'});
  await page.reload();
  await choose(page, project);
  await page.locator('[data-view="entries"]').click();
  await page.getByRole('button', {name: 'Titre initial', exact: true}).click();
  await page.getByRole('button', {name: 'Modifier', exact: true}).click();
  await page.getByLabel('Titre', {exact: true}).fill('Mon brouillon');
  await patch(page, project, entry, {body: 'Texte changé ailleurs'});
  await page.getByRole('button', {name: 'Enregistrer la révision', exact: true}).click();
  const error = page.locator('#form-error');
  await expect(error).toContainText('modifiée entre-temps');
  await expect(error).not.toContainText('Entry changed');
  await expect(error).not.toContainText('reload it');
  await error.getByRole('button', {name: 'Charger la version actuelle'}).click();
  await expect(error).toContainText('Texte changé ailleurs');
  await expect(page.getByLabel('Titre', {exact: true})).toHaveValue('Mon brouillon');
  await expect(page.locator('#entry-form [name="revision"]')).toHaveValue('2');
  await page.getByRole('button', {name: 'Enregistrer la révision', exact: true}).click();
  await expect(page.locator('#toast')).toContainText('Nouvelle révision enregistrée');
  await expect(page.locator('#detail .detail-title')).toHaveText('Mon brouillon');
  await expect(page.locator('#detail')).toContainText('Révision 3');
  await context.close();
});

test('D-2: reviewing a proposal that was reviewed elsewhere explains it and stops', async ({page}) => {
  await open(page);
  const project = await newProject(page, `Revue ${Date.now()}`);
  const entry = await newEntry(page, project, 'À examiner deux fois');
  await page.reload();
  await choose(page, project);
  await page.locator('[data-view="entries"]').click();
  await page.getByRole('button', {name: 'À examiner deux fois', exact: true}).click();
  await page.getByRole('button', {name: 'Accepter', exact: true}).click();
  await accept(page, project, entry);
  await page.getByRole('button', {name: 'Confirmer l’acceptation', exact: true}).click();
  await expect(page.locator('#form-error')).toContainText('modifiée entre-temps');
  await page.getByRole('button', {name: 'Charger la version actuelle'}).click();
  await expect(page.locator('#form-error')).toContainText('déjà été examinée');
  await expect(page.getByRole('button', {name: 'Confirmer l’acceptation', exact: true})).toBeDisabled();
});

for (const [width, height] of [[375, 740], [768, 900], [1440, 1000]]) {
  test(`D-4: ${width}px layout reaches Git, add and every tab without overlap or overflow`, async ({page}) => {
    const problems = watch(page);
    await page.setViewportSize({width, height});
    await open(page);
    const project = await newProject(page, `Mise en page ${width} ${Date.now()}`);
    await newEntry(page, project, 'Une connaissance', {kind: 'observation'});
    await page.reload();
    await choose(page, project);
    await expect(page.locator('.knowledge-row').first()).toBeVisible();
    await page.screenshot({path: path.join(shots, `layout-${width}-overview.png`), fullPage: true});
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(await overlaps(page, ['.brand', '#git-open', '.project-switch select', '#new-project', '#nav', '#capture-pill', '#export', '#add-entry'])).toEqual([]);
    // Git is a real, sized, hit-testable control inside the viewport.
    const box = await page.locator('#git-open').boundingBox();
    // WCAG 2.2 target size: at least 24px everywhere, a comfortable 40px for touch.
    expect(box.width).toBeGreaterThanOrEqual(24);
    expect(box.height).toBeGreaterThanOrEqual(width <= 650 ? 40 : 24);
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width);
    expect(await page.evaluate(() => { const r = document.querySelector('#git-open').getBoundingClientRect(); return !!document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)?.closest('#git-open'); })).toBe(true);
    // The add control is reachable, not covered by a tab.
    await expect(page.locator('#new-project')).toBeVisible();
    const add = await page.locator('#new-project').boundingBox();
    expect(add.width).toBeGreaterThanOrEqual(24);
    expect(add.height).toBeGreaterThanOrEqual(24);
    // Every tab can be scrolled to and used; the strip tells when there is more to the side.
    for (const view of ['overview', 'entries', 'timeline', 'graph', 'handoff', 'import', 'capture']) {
      const tab = page.locator(`.nav-item[data-view="${view}"]`);
      await tab.scrollIntoViewIfNeeded();
      const rect = await tab.boundingBox();
      expect(rect.x).toBeGreaterThanOrEqual(-1);
      expect(rect.x + rect.width).toBeLessThanOrEqual(width + 1);
      await tab.click();
      await expect(page.locator('#nav .nav-item.active')).toHaveAttribute('data-view', view);
    }
    if (width <= 650) {
      const strip = await page.locator('#nav').evaluate(el => ({overflow: el.scrollWidth > el.clientWidth, mask: getComputedStyle(el).maskImage || getComputedStyle(el).webkitMaskImage}));
      expect(strip.overflow).toBe(true);
      expect(strip.mask).toContain('gradient');
    }
    await page.screenshot({path: path.join(shots, `layout-${width}-capture.png`), fullPage: true});
    await page.locator('#git-open').click();
    await expect(page.locator('#modal-title')).toHaveText('Versionner la mémoire');
    await page.screenshot({path: path.join(shots, `layout-${width}-git.png`)});
    expect(problems).toEqual([]);
  });
}

test('D-5: a project created in the background joins the selector without touching selection or draft', async ({page}) => {
  await open(page);
  const current = await newProject(page, `Courant ${Date.now()}`);
  await page.reload();
  await choose(page, current);
  await page.locator('#add-entry').click();
  await page.getByLabel('Titre', {exact: true}).fill('Brouillon à ne pas écraser');
  await page.getByLabel('Contenu et raisons').fill('Texte en cours');
  const before = await page.locator('#project-select option').count();
  const created = await newProject(page, `Créé par la capture ${Date.now()}`);
  await expect(page.locator('#project-select option')).toHaveCount(before + 1, {timeout: 15000});
  await expect(page.locator(`#project-select option[value="${created.id}"]`)).toHaveText(created.name);
  await expect(page.getByLabel('Projet actif')).toHaveValue(current.id);
  await expect(page.locator('#project-name')).toHaveText(current.name);
  await expect(page.locator('#entry-form [name="title"]')).toHaveValue('Brouillon à ne pas écraser');
  await expect(page.locator('#entry-form [name="body"]')).toHaveValue('Texte en cours');
});

test('D-5: from the empty welcome screen, the first auto-created project appears and is selected', async ({page}) => {
  const empty = await startServer('empty');
  try {
    await open(page, empty);
    await expect(page.getByRole('heading', {name: 'Bienvenue dans Filigree.'})).toBeVisible();
    const project = await newProject(page, 'Première capture', empty);
    await expect(page.locator('#project-name')).toHaveText('Première capture', {timeout: 15000});
    await expect(page.getByLabel('Projet actif')).toHaveValue(project.id);
  } finally { empty.child.kill(); }
});

test('D-6: native and tap proposals are labelled for what they are, with honest counts and no raw JSON', async ({page}) => {
  const problems = watch(page);
  await open(page);
  await page.getByLabel('Projet actif').selectOption({label: 'Projet capturé'});
  await expect(page.locator('#project-name')).toHaveText('Projet capturé');
  await page.locator('[data-view="entries"]').click();
  const native = page.locator('.knowledge-row', {hasText: 'Je choisis SQLite'});
  const tap = page.locator('.knowledge-row', {hasText: 'Quelle base choisir'});
  await expect(native.locator('.entry-meta')).toContainText(/1 source(?!s)/);
  await expect(native.locator('.entry-meta')).not.toContainText('4 sources');
  await expect(tap.locator('.entry-meta')).toContainText(/1 source(?!s)/);
  await native.getByRole('button', {name: /Je choisis SQLite/}).click();
  const detail = page.locator('#detail');
  await expect(detail).toContainText('Transcription locale Claude Code');
  await expect(detail).toContainText('Provenance de la capture');
  await expect(detail).toContainText('Reconnu grâce au dossier de la session');
  await expect(detail).toContainText('non authentifiées');
  await expect(detail.locator('.source-card strong').filter({hasText: /^claude-tap$/})).toHaveCount(0);
  expect(await detail.locator('.technical').count()).toBeGreaterThan(0);
  await expect(detail.locator('.technical[open]')).toHaveCount(0);
  await expect(detail.locator('.technical-data:visible')).toHaveCount(0);
  expect(await detail.evaluate(el => [...el.querySelectorAll('.technical-data')].every(pre => !pre.checkVisibility()))).toBe(true);
  await page.screenshot({path: path.join(shots, 'native-detail.png')});
  await page.keyboard.press('Escape');
  await tap.getByRole('button', {name: /Quelle base choisir/}).click();
  await expect(detail).toContainText('Trace claude-tap (capture automatique)');
  await expect(detail).toContainText('claude-tap · claude · abcd1234 #1');
  // Source text stays inert data.
  await expect(detail.locator('img')).toHaveCount(0);
  await expect(detail.locator('.detail-body-text')).toContainText('<img src=x onerror="window.pwned=1">');
  expect(await page.evaluate(() => window.pwned)).toBeUndefined();
  expect(problems).toEqual([]);
});

test('D-7: Escape, the backdrop and Annuler ask before discarding a draft', async ({page}) => {
  await open(page);
  const project = await newProject(page, `Brouillon ${Date.now()}`);
  await page.reload();
  await choose(page, project);
  const messages = [];
  let answer = false;
  page.on('dialog', async dialog => { messages.push(dialog.message()); await (answer ? dialog.accept() : dialog.dismiss()); });
  // No draft: Escape closes at once, without a question.
  await page.locator('#add-entry').click();
  await page.keyboard.press('Escape');
  await expect(page.locator('#modal')).not.toHaveAttribute('open', '');
  expect(messages).toEqual([]);
  // A draft: refused, twice in a row, then through the backdrop and Annuler.
  await page.locator('#add-entry').click();
  await page.getByLabel('Titre', {exact: true}).fill('Un brouillon précieux');
  await page.keyboard.press('Escape');
  await page.keyboard.press('Escape');
  await expect.poll(() => messages.length).toBe(2);
  await expect(page.locator('#modal')).toHaveAttribute('open', '');
  await page.mouse.click(4, 4);
  await expect.poll(() => messages.length).toBe(3);
  await page.getByRole('button', {name: 'Annuler', exact: true}).click();
  await expect.poll(() => messages.length).toBe(4);
  await expect(page.getByLabel('Titre', {exact: true})).toHaveValue('Un brouillon précieux');
  expect(messages.every(message => message.includes('saisie non enregistrée'))).toBe(true);
  // Confirmed: it closes.
  answer = true;
  await page.keyboard.press('Escape');
  await expect(page.locator('#modal')).not.toHaveAttribute('open', '');
});

test('P3: search ignores accents, case and surrounding spaces; empty states tell the truth', async ({page}) => {
  await open(page);
  const project = await newProject(page, `Recherche ${Date.now()}`);
  await page.reload();
  await choose(page, project);
  await page.locator('[data-view="entries"]').click();
  await expect(page.locator('#entries-results')).toContainText('Aucune connaissance pour le moment');
  await expect(page.locator('#entries-results')).not.toContainText('Modifiez les filtres');
  await newEntry(page, project, 'Éléphant au café', {kind: 'observation'});
  await newEntry(page, project, 'Autre sujet', {kind: 'observation'});
  await page.reload();
  await page.locator('[data-view="entries"]').click();
  for (const query of ['elephant', 'ELEPHANT', ' cafe ', 'éléphant', 'CAFÉ']) {
    await page.getByRole('searchbox').fill(query);
    await expect(page.locator('.knowledge-row')).toHaveCount(1);
    await expect(page.locator('.knowledge-row')).toContainText('Éléphant au café');
  }
  await page.getByRole('searchbox').fill('introuvable');
  await expect(page.locator('#entries-results')).toContainText('Aucune connaissance ne correspond à ces filtres');
});

test('P3: technical or English failures reach the user in French; busy and stale states are handled', async ({page}) => {
  await open(page);
  const project = await newProject(page, `Messages ${Date.now()}`);
  await page.reload();
  await choose(page, project);
  await expect(page).toHaveTitle(new RegExp(`Vue d’ensemble — ${project.name} — Filigree`));
  // Raw backend text never reaches the form.
  let reply = {status: 400, error: 'Traceback (most recent call last): KeyError: x'};
  await page.route('**/api/projects/*/entries', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    await route.fulfill({status: reply.status, contentType: 'application/json', body: JSON.stringify({error: reply.error})});
  });
  await page.locator('#add-entry').click();
  await page.getByLabel('Titre', {exact: true}).fill('Titre');
  await page.getByLabel('Contenu et raisons').fill('Corps');
  const submit = page.getByRole('button', {name: 'Ajouter la connaissance', exact: true});
  await submit.click();
  await expect(page.locator('#form-error')).toContainText('Cette demande n’est pas valide');
  await expect(page.locator('#form-error')).not.toContainText('Traceback');
  reply = {status: 404, error: 'Project not found'};
  await submit.click();
  await expect(page.locator('#form-error')).toContainText('introuvable');
  await expect(page.locator('#form-error')).not.toContainText('Project not found');
  await page.unroute('**/api/projects/*/entries');
  await page.evaluate(() => { const modal = document.querySelector('#modal'); if (modal.open) modal.close(); });
  // Busy state during an import, and no stale error from the attempt before.
  let attempt = 0;
  await page.route('**/api/projects/*/import', async route => {
    attempt++;
    if (attempt === 1) return route.fulfill({status: 400, contentType: 'application/json', body: JSON.stringify({error: 'La note est vide.'})});
    await new Promise(resolve => setTimeout(resolve, 1200));
    await route.continue();
  });
  await page.locator('[data-view="import"]').click();
  await page.getByLabel('Texte ou traces').fill('Une note à importer');
  const importButton = page.getByRole('button', {name: 'Importer les traces', exact: true});
  await importButton.click();
  await expect(page.locator('#import-error')).toContainText('La note est vide.');
  await importButton.click();
  await expect(page.locator('#import-error')).toBeEmpty();
  await expect(page.locator('#import-form [type="submit"]')).toBeDisabled();
  await expect(page.locator('#import-form [type="submit"]')).toHaveText('Importation en cours…');
  await expect(page.locator('#import-form')).toHaveAttribute('aria-busy', 'true');
  await expect(page.locator('#import-result')).toContainText('1 connaissance importée', {timeout: 10000});
  // A toast belongs to the view it was shown in.
  await expect(page.locator('#toast')).toHaveClass(/visible/);
  await page.locator('[data-view="timeline"]').click();
  await expect(page.locator('#toast')).not.toHaveClass(/visible/);
  await expect(page).toHaveTitle(new RegExp(`Chronologie — ${project.name} — Filigree`));
});

test('D12: a server started without capture says so and offers no capture control to click', async ({page}) => {
  await open(page);
  const project = await newProject(page, `Sans capture ${Date.now()}`);
  const posts = [];
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/api/capture')) posts.push(request.url()); });
  await page.reload();
  await choose(page, project);
  await page.locator('[data-view="capture"]').click();
  await expect(page.locator('#capture-banner')).toContainText('Capture désactivée');
  await expect(page.locator('#capture-controls')).toContainText('--no-capture');
  await expect(page.locator('#capture-controls button')).toHaveCount(0);
  expect(posts).toEqual([]);
});

test('P3: capture controls are coherent when disabled and warn before excluding the project’s own folder', async ({page}) => {
  await open(page);
  const project = await newProject(page, `Contrôles ${Date.now()}`);
  const status = {enabled: false, paused_all: false, auto_create: true, settings_error: null, running: false, in_process: true,
    tap: {path: 'synthetic/traces.sqlite3', capability: 'missing', sessions: 0, baselined: false}, native: {index: true, fallback: false, roots: {}},
    counters: {}, skipped: {}, malformed: {}, notices: [], last_scan: null, paused: [], exclude: [], mappings: 0, pending: []};
  const posts = [];
  let current = status;
  await page.route('**/api/capture', async route => {
    if (route.request().method() === 'POST') { posts.push(route.request().postDataJSON()); return route.fulfill({json: {ok: true, status: current}}); }
    await route.fulfill({json: current});
  });
  await page.reload();
  await choose(page, project);
  await page.locator('[data-view="capture"]').click();
  await expect(page.getByRole('button', {name: 'Suspendre', exact: true})).toBeDisabled();
  current = {...status, enabled: true, running: true};
  await expect(page.getByRole('button', {name: 'Suspendre', exact: true})).toBeEnabled({timeout: 15000});
  const own = await page.locator('.folder-line code').first().innerText();
  const messages = [];
  page.on('dialog', async dialog => { messages.push(dialog.message()); await dialog.dismiss(); });
  await page.getByLabel('Dossier à exclure').fill(own);
  await page.getByRole('button', {name: 'Exclure ce dossier', exact: true}).click();
  await expect.poll(() => messages.length).toBe(1);
  expect(messages[0]).toContain('celui du projet');
  expect(posts).toEqual([]);
});

test('P3: a large memory gives a bounded, filterable, usable graph', async ({page}) => {
  const problems = watch(page);
  await open(page);
  const project = await newProject(page, `Grand graphe ${Date.now()}`);
  const events = Array.from({length: 300}, (_, i) => ({title: `Observation ${i} marque-${i}`, body: `Contenu ${i}`}));
  const imported = await call(page, 'POST', `/api/projects/${project.id}/import`, {text: JSON.stringify(events), source: 'volume', format: 'auto'});
  expect(imported.status).toBe(200);
  const listed = (await call(page, 'GET', `/api/projects/${project.id}/entries`)).body;
  const entries = Array.isArray(listed) ? listed : listed.entries;
  expect(entries.length).toBe(300);
  const far = entries.filter(entry => /marque-(27\d)$/.test(entry.title));
  for (let i = 0; i + 1 < far.length; i += 2) await patch(page, project, far[i], {relations: [{target: far[i + 1].id, type: 'relates_to'}]});
  await page.reload();
  await choose(page, project);
  await page.locator('[data-view="graph"]').click();
  const nodes = page.locator('.graph-node');
  await expect(nodes.first()).toBeVisible();
  expect(await nodes.count()).toBeLessThanOrEqual(48);
  await expect(page.locator('.graph-legend [role="status"]')).toContainText('sur 300');
  expect(await page.locator('.graph-line').count()).toBeGreaterThan(0);
  // Linked knowledge comes first even if it lies far down the list.
  await expect(page.locator('.graph-node', {hasText: 'marque-270'})).toHaveCount(1);
  const surface = await page.locator('.graph-surface').boundingBox();
  expect(surface.height).toBeLessThanOrEqual(1000 * 0.7 + 2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path: path.join(shots, 'graph-300.png')});
  // Filter finds anything; "more" extends the bounded page.
  await page.getByLabel('Filtrer le graphe', {exact: true}).fill('marque-155');
  await expect(nodes).toHaveCount(1);
  await page.getByLabel('Filtrer le graphe', {exact: true}).fill('');
  const before = await nodes.count();
  await page.getByRole('button', {name: /Afficher \d+ de plus/}).click();
  expect(await nodes.count()).toBeGreaterThan(before);
  expect(await nodes.count()).toBeLessThanOrEqual(96);
  // Keyboard access to a node still opens its sheet.
  await nodes.first().focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#detail')).toBeVisible();
  expect(problems).toEqual([]);
});
