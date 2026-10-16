const fs = require('fs');
const path = require('path');
const { test, expect } = require('@playwright/test');

// Real temporary folders, created by playwright.config.cjs outside the memory root.
const makeFolder = label => {
  const folder = path.join(process.env.FILIGREE_BROWSER_FOLDERS, `${label}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`);
  fs.mkdirSync(folder, {recursive: true});
  return folder;
};
const apiProject = (page, name, folder) => page.evaluate(async ({name, folder}) => {
  const {token} = await (await fetch('/api/bootstrap')).json();
  const response = await fetch('/api/projects', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Filigree-Token': token}, body: JSON.stringify({name, folder, description: ''})});
  return response.json();
}, {name, folder});

test('human review, historical alternatives, graph and portable handoff', async ({page}) => {
  const errors=[];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByRole('button', {name:'Créer un projet',exact:true}).click();
  const name=`Reprise vérifiée ${Date.now()}`;
  const folder=makeFolder('reprise');
  await page.getByLabel('Nom du projet',{exact:true}).fill(name);
  await page.getByLabel('Dossier du projet').fill(folder);
  await page.getByLabel('Intention du projet').fill('Transmettre une compréhension corrigée.');
  await page.getByRole('button',{name:'Créer le projet',exact:true}).click();
  await expect(page.locator('#project-name')).toHaveText(name);
  await expect(page.locator('.folder-line code')).toHaveText(fs.realpathSync.native(folder));
  await page.locator('#add-entry').click();
  await page.getByLabel('Titre',{exact:true}).fill('Choisir Basic Memory');
  await page.getByLabel('Contenu et raisons').fill('Proposition initiale à examiner.');
  await page.getByLabel('Type',{exact:true}).selectOption('hypothesis');
  await page.getByRole('button',{name:'Ajouter la connaissance',exact:true}).click();
  await page.getByRole('button',{name:'Choisir Basic Memory',exact:true}).first().click();
  // A proposal cannot be replaced (A8): the human accepts the original first, then replaces it.
  await page.locator('#detail-content').getByRole('button',{name:'Accepter',exact:true}).click();
  await page.getByRole('button',{name:'Confirmer l’acceptation',exact:true}).click();
  await expect(page.locator('#modal')).not.toBeVisible();
  await page.getByRole('button',{name:'Remplacer',exact:true}).click();
  await page.getByLabel('Titre',{exact:true}).fill('La méthode avant les outils');
  await page.getByLabel('Contenu et raisons').fill('Le choix de Basic Memory reste suspendu.');
  await page.getByRole('button',{name:'Ajouter la connaissance',exact:true}).click();
  await page.locator('[data-view="handoff"]').click();
  await expect(page.locator('.code-output')).toContainText('La méthode avant les outils');
  await expect(page.locator('.code-output')).toContainText('Choisir Basic Memory');
  await expect(page.locator('.code-output')).toContainText('NOT CURRENT');
  await page.locator('[data-view="graph"]').click();
  await expect(page.locator('.graph-surface svg')).toBeVisible();
  await expect(page.locator('.graph-line')).toHaveCount(1);
  await page.locator('[data-view="import"]').click();
  await page.getByLabel('Texte ou traces').fill('Une note humaine à examiner');
  await page.getByRole('button',{name:'Importer les traces',exact:true}).click();
  await expect(page.locator('#import-result')).toContainText('1');
  await page.locator('[data-view="entries"]').click();
  await page.getByRole('searchbox').fill('Une note humaine');
  await expect(page.locator('.knowledge-row')).toHaveCount(1);
  await page.locator('[data-view="timeline"]').click();
  await expect(page.locator('.timeline-full')).toContainText('Traces importées');
  await expect(page.locator('.timeline-full')).not.toContainText('events.imported');
  await page.reload();
  await expect(page.locator('#project-name')).toHaveText(name);
  expect(errors).toEqual([]);
});

test('project creation refuses a missing, relative or absent folder with a clear message', async ({page}) => {
  await page.goto('/');
  await page.locator('#new-project').click();
  await page.getByLabel('Nom du projet',{exact:true}).fill(`Sans dossier ${Date.now()}`);
  for (const [folder, message] of [['relatif/dossier', /chemin absolu/], [path.join(process.env.FILIGREE_BROWSER_FOLDERS, 'absent-pour-de-bon'), /n'existe pas/]]) {
    await page.getByLabel('Dossier du projet').fill(folder);
    await page.getByRole('button',{name:'Créer le projet',exact:true}).click();
    await expect(page.locator('#form-error')).toContainText(message);
  }
});

test('background refresh shows new knowledge without losing an unsaved form', async ({page}) => {
  await page.goto('/');
  const name=`Capture vivante ${Date.now()}`;
  const project=await apiProject(page, name, makeFolder('vivante'));
  await page.reload();
  await page.getByLabel('Projet actif').selectOption(project.id);
  await expect(page.locator('#project-name')).toHaveText(name);
  await page.locator('#add-entry').click();
  await page.getByLabel('Titre',{exact:true}).fill('Brouillon en cours de saisie');
  await page.getByLabel('Contenu et raisons').fill('Texte non enregistré');
  // What automatic capture does: new proposals arrive while the user is typing.
  await page.evaluate(async id => {
    const {token} = await (await fetch('/api/bootstrap')).json();
    await fetch(`/api/projects/${id}/import`, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Filigree-Token': token}, body: JSON.stringify({format: 'text', source: 'capture simulée', text: 'Observation arrivée en arrière-plan'})});
  }, project.id);
  await expect(page.locator('#nav-count')).toHaveText('1', {timeout: 15000});
  await expect(page.getByLabel('Titre',{exact:true})).toHaveValue('Brouillon en cours de saisie');
  await expect(page.getByLabel('Contenu et raisons')).toHaveValue('Texte non enregistré');
});

test('switching project asks before discarding an import draft and keeps it when declined', async ({page}) => {
  await page.goto('/');
  const names={first:`Brouillon A ${Date.now()}`, second:`Brouillon B ${Date.now()}`};
  const first=await apiProject(page, names.first, makeFolder('brouillon-a'));
  const second=await apiProject(page, names.second, makeFolder('brouillon-b'));
  await page.reload();
  await page.getByLabel('Projet actif').selectOption(first.id);
  await expect(page.locator('#project-name')).toHaveText(names.first);
  await page.locator('[data-view="import"]').click();
  await page.locator('#import-form [name="text"]').fill('Brouillon à ne pas perdre');
  const messages=[];
  let accept=false;
  page.on('dialog', async dialog => { messages.push(dialog.message()); await (accept ? dialog.accept() : dialog.dismiss()); });
  await page.getByLabel('Projet actif').selectOption(second.id);
  await expect.poll(() => messages.length).toBe(1);
  await expect(page.locator('#project-name')).toHaveText(names.first);
  await expect(page.getByLabel('Projet actif')).toHaveValue(first.id);
  await expect(page.locator('#import-form [name="text"]')).toHaveValue('Brouillon à ne pas perdre');
  accept=true;
  await page.getByLabel('Projet actif').selectOption(second.id);
  await expect(page.locator('#project-name')).toHaveText(names.second, {timeout: 10000});
});

test('switching project blocks writes until the new project is loaded and keeps the selector on the target', async ({page}) => {
  await page.goto('/');
  const names={first:`Premier ${Date.now()}`, second:`Second ${Date.now()}`};
  const first=await apiProject(page, names.first, makeFolder('premier'));
  const second=await apiProject(page, names.second, makeFolder('second'));
  await page.reload();
  await page.getByLabel('Projet actif').selectOption(first.id);
  await expect(page.locator('#project-name')).toHaveText(names.first);
  const writes=[];
  page.on('request', request => { if (request.method()!=='GET' && request.url().includes('/api/projects/')) writes.push(request.url()); });
  await page.route(`**/api/projects/${second.id}/entries`, async route => { await new Promise(resolve => setTimeout(resolve, 1500)); await route.continue(); });
  await page.getByLabel('Projet actif').selectOption(second.id);
  // The request is still in flight: the title is still the previous project, the selector shows the target, writing is off.
  await expect(page.locator('#project-name')).toHaveText(names.first);
  await expect(page.getByLabel('Projet actif')).toHaveValue(second.id);
  await expect(page.locator('#add-entry')).toBeDisabled();
  await expect(page.locator('#project-name')).toHaveText(names.second, {timeout: 10000});
  await expect(page.locator('#add-entry')).toBeEnabled();
  await page.locator('#add-entry').click();
  await page.getByLabel('Titre',{exact:true}).fill('Pour le second projet');
  await page.getByLabel('Contenu et raisons').fill('Cette saisie vise le projet affiché.');
  await page.getByRole('button',{name:'Ajouter la connaissance',exact:true}).click();
  await expect(page.locator('#toast')).toContainText('Connaissance ajoutée');
  expect(writes.filter(url => url.includes(first.id))).toEqual([]);
  expect(writes.filter(url => url.includes(second.id)).length).toBeGreaterThan(0);
});

test('capture view reports the monitor, the claude-tap source and maps a pending session', async ({page}) => {
  await page.goto('/');
  const name=`Rattachement ${Date.now()}`;
  const project=await apiProject(page, name, makeFolder('rattachement'));
  const status={enabled:true,paused_all:false,auto_create:true,settings_error:null,running:true,in_process:true,
    tap:{path:'synthetic/traces.sqlite3',capability:'ok',sessions:2,baselined:true},native:{index:true,fallback:false,roots:{}},
    counters:{imported:3,duplicates:1},skipped:{},malformed:{},notices:[],last_scan:null,paused:[],exclude:[],mappings:0,
    pending:[{key:'tap:SYNTH-1',client:'claude',reason:'no_native_id',count:2,sessions:1,first_ts:'2026-10-16T10:00:00+00:00',last_ts:'2026-10-16T10:05:00+00:00',history:false,overflow:false}]};
  const posts=[];
  let linked=false;
  await page.route('**/api/capture', async route => {
    if (route.request().method()==='POST') { posts.push(route.request().postDataJSON()); linked=true; await route.fulfill({json:{ok:true,status:{...status,pending:[]}}}); }
    else await route.fulfill({json:{...status,pending:linked?[]:status.pending}});
  });
  await page.reload();
  await page.getByLabel('Projet actif').selectOption(project.id);
  await page.locator('.nav-item[data-view="capture"]').click();
  await expect(page.locator('.capture-state')).toContainText('Capture active');
  await expect(page.locator('.tap-state')).toContainText('Connecté en lecture seule');
  await expect(page.locator('#capture-pending')).toContainText('La trace ne porte aucun identifiant de session natif.');
  await expect(page.locator('#capture-pending')).toContainText('Aucun contenu n’est conservé');
  await page.locator('#capture-pending select').selectOption(project.id);
  await page.getByRole('button',{name:'Rattacher',exact:true}).click();
  await expect(page.locator('#toast')).toContainText('Session rattachée');
  expect(posts).toEqual([{action:'link',key:'tap:SYNTH-1',project_id:project.id,import_history:false}]);
  await expect(page.locator('.no-pending')).toBeVisible();
  // The exclusion form keeps what is typed while the status refreshes.
  await page.getByLabel('Dossier à exclure').fill('C:\\en-cours-de-saisie');
  await page.waitForTimeout(7000);
  await expect(page.getByLabel('Dossier à exclure')).toHaveValue('C:\\en-cours-de-saisie');
});

test('demo, hostile content escaping and mobile layout', async ({page}) => {
  await page.goto('/');
  await page.evaluate(async()=>{
    const {token}=await (await fetch('/api/bootstrap')).json();
    await fetch('/api/demo',{method:'POST',headers:{'Content-Type':'application/json','X-Filigree-Token':token},body:'{}'});
  });
  await page.reload();
  await page.getByLabel('Projet actif').selectOption({label:"La mémoire d'un projet"});
  // The selector changes at once; the title, the folder and the data follow only when the request ends.
  await expect(page.locator('#project-name')).toHaveText("La mémoire d'un projet");
  await expect(page.locator('#add-entry')).toBeEnabled();
  await expect(page.getByRole('heading',{name:'Gardez le fil de vos idées.'})).toBeVisible();
  await expect(page.locator('.folder-line code')).toContainText('filigree-demo-');
  // The README screenshot: the synthetic demo project, regenerated by every browser run.
  await page.screenshot({path:'.github/assets/workbench.png',fullPage:true});
  await page.locator('#add-entry').click();
  await page.getByLabel('Titre',{exact:true}).fill('<img src=x onerror=alert(1)>');
  await page.getByLabel('Contenu et raisons').fill('<script>window.pwned=true</script>');
  await page.getByRole('button',{name:'Ajouter la connaissance',exact:true}).click();
  await expect(page.getByRole('button',{name:'<img src=x onerror=alert(1)>',exact:true}).first()).toBeVisible();
  expect(await page.evaluate(()=>window.pwned)).toBeUndefined();
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'.runtime/mobile.png',fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
});

// INT-2, deterministic: the bootstrap answer (which carries the mutation token) is held back while the user already
// submits the form. The write must wait for the token, and the NEW project (not another one) must end up selected,
// even though earlier projects exist in the same data directory.
test('project creation waits for a delayed bootstrap and keeps the new project selected', async ({page}) => {
  await page.goto('/');
  await apiProject(page, 'Projet déjà présent', makeFolder('existant'));
  let released = false;
  await page.route('**/api/bootstrap', async route => { await new Promise(resolve => setTimeout(resolve, 1500)); released = true; await route.continue(); });
  const created = [];
  page.on('response', response => { if (response.request().method() === 'POST' && response.url().endsWith('/api/projects')) created.push(response.status()); });
  await page.goto('/', {waitUntil: 'commit'});
  await page.getByRole('button', {name: 'Créer un projet', exact: true}).click();
  const name = `Création différée ${Date.now()}`;
  await page.getByLabel('Nom du projet', {exact: true}).fill(name);
  await page.getByLabel('Dossier du projet').fill(makeFolder('differee'));
  await page.getByRole('button', {name: 'Créer le projet', exact: true}).click();
  await expect(page.locator('#project-name')).toHaveText(name, {timeout: 15000});
  expect(released).toBe(true);
  expect(created).toEqual([201]);
});
