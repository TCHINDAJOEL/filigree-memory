const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { test, expect } = require('@playwright/test');

// A synthetic journal written through Filigree's own ActivityLog, then read by the workbench (no agent, no real transcript).
const seedJournal = (projectId, events) => execFileSync('python', ['-c', [
  'import json, sys',
  'from pathlib import Path',
  'from filigree.activity import ActivityLog, journal_path',
  'from filigree.store import Store',
  'store = Store(sys.argv[1])',
  'for session, items in json.loads(sys.argv[3]).items():',
  '    ActivityLog(journal_path(store, sys.argv[2])).add({"session_key": session, "client": "claude"}, items)',
].join('\n'), process.env.FILIGREE_BROWSER_MEMORY, projectId, JSON.stringify(events)], {env: {...process.env, PYTHONPATH: path.resolve('.')}});

test('activity view shows unreviewed events, active sessions and overlaps, with hostile text kept inert', async ({page}) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  const folder = path.join(process.env.FILIGREE_BROWSER_FOLDERS, `activite-${Date.now()}`);
  fs.mkdirSync(folder, {recursive: true});
  const project = await page.evaluate(async folder => {
    const {token} = await (await fetch('/api/bootstrap')).json();
    return (await fetch('/api/projects', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Filigree-Token': token}, body: JSON.stringify({name: 'Activité visible', folder, description: ''})})).json();
  }, folder);
  const now = new Date().toISOString().slice(0, 19) + '+00:00';
  const shared = path.join(folder, 'shared.py');
  seedJournal(project.id, {
    'claude:abc:S-one': [{event_id: 'e1', kind: 'user_prompt', ts_observed: now, summary: 'Corrige <img src=x onerror=window.pwned=1> l’export'},
                         {event_id: 'e2', kind: 'file_change', ts_observed: now, summary: 'Write · shared.py', files: [shared]}],
    'claude:abc:S-two': [{event_id: 'e3', kind: 'file_change', ts_observed: now, summary: 'Edit · shared.py', files: [shared]},
                         {event_id: 'e4', kind: 'test_result', ts_observed: now, summary: 'échec · pytest · 1 failed'}],
  });
  await page.evaluate(id => localStorage.setItem('filigree.project', id), project.id);
  await page.goto('/#activity');
  await page.reload();  // a hash-only navigation does not reload the page
  await expect(page.locator('#project-name')).toHaveText('Activité visible');
  await expect(page.locator('#view-name')).toHaveText('Activité');
  await expect(page.locator('.activity-feed')).toBeVisible();
  await expect(page.getByText('Données d’activité non revues', {exact: false}).or(page.getByText("Données d'activité non revues", {exact: false}))).toBeVisible();
  await expect(page.locator('.activity-event')).toHaveCount(4);
  await expect(page.locator('.callout.warning')).toContainText('shared.py');
  await expect(page.locator('.activity-list li')).toHaveCount(2);
  await expect(page.locator('.activity-feed')).toContainText('<img src=x onerror=window.pwned=1>');
  expect(await page.evaluate(() => window.pwned)).toBeUndefined();
  await page.setViewportSize({width: 375, height: 800});
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});
