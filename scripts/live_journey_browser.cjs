// Browser half of scripts/verify_live_journey.py. Real Playwright Chromium against the isolated local server only.
// Usage: node scripts/live_journey_browser.cjs <config.json>   (the config and the result stay under .runtime)
// Modes: "review" finds the captured proposal in the page, checks its visible provenance, converts it to a decision
// when needed and accepts it with an explicit reason; "scan" walks every view and the accepted sheet looking for the
// raw fake credentials. It never prints page text: the result file holds booleans, counts and timings.
const fs = require('fs');
const path = require('path');
const {chromium} = require('@playwright/test');

const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = {mode: config.mode, ok: false, timings: {}, checks: {}, leaks: 0, scans: 0, page_errors: 0, screenshots: []};
const stamp = Date.now();
const lap = name => { out.timings[name] = Date.now() - stamp; };
const finish = code => { fs.writeFileSync(config.result, JSON.stringify(out, null, 1)); process.exitCode = code; };

async function scan(page) {
  const text = await page.evaluate(() => document.documentElement.textContent);
  out.scans += 1;
  out.leaks += config.needles.filter(needle => text.includes(needle)).length;
}
async function shot(page, name, options = {}) {
  const file = path.join(config.shots, `${config.prefix}-${name}.png`);
  await page.screenshot({path: file, ...options});
  out.screenshots.push(file);
}
async function ready(page) {
  await page.goto(config.origin + '/');
  await page.locator('#main[aria-busy="false"]').waitFor({timeout: 20000});
  await page.getByLabel('Projet actif').selectOption(config.projectId);
  await page.locator('[data-view="entries"]').click();
}

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await (await browser.newContext({viewport: {width: 1440, height: 1000}})).newPage();
    page.on('pageerror', () => { out.page_errors += 1; });
    page.setDefaultTimeout(20000);
    await ready(page);
    lap('opened');
    const title = page.locator(`.entry-title[data-entry="${config.entryId}"]`);
    if (config.mode === 'review') {
      await title.waitFor();
      out.checks.proposal_found_in_list = true;
      out.checks.proposal_row_shows_status = await page.locator('.knowledge-row', {has: title}).innerText().then(text => /À examiner/.test(text));
      await shot(page, '1-list');
      await title.click();
      const detail = page.locator('#detail');
      await detail.locator('.detail-title').waitFor();
      const visible = await detail.innerText();
      out.checks.provenance_card = visible.includes('Provenance de la capture');
      out.checks.origin_tap = visible.includes('Trace claude-tap (capture automatique)');
      out.checks.session_id_visible = visible.includes(config.nativeId);
      out.checks.folder_visible = visible.toLowerCase().includes(config.folderName.toLowerCase());
      out.checks.unauthenticated_notice = visible.includes('non authentifiées');
      await scan(page);
      await shot(page, '2-provenance');
      lap('inspected');
      if (config.convert) {
        await detail.locator('button[data-edit]').click();
        await page.locator('#modal select[name="kind"]').selectOption('decision');
        await page.locator('#modal textarea[name="reason"]').fill(config.convertReason);
        await shot(page, '3-convert-form');
        await page.getByRole('button', {name: 'Enregistrer la révision', exact: true}).click();
        await page.locator('#toast', {hasText: 'Nouvelle révision enregistrée'}).waitFor();
        out.checks.converted_through_ui = true;
        if (!(await detail.evaluate(element => element.open))) { await title.click(); await detail.locator('.detail-title').waitFor(); }
        lap('converted');
      }
      await detail.locator('button[data-accept]').click();
      await page.locator('#modal textarea[name="reason"]').fill(config.acceptReason);
      await shot(page, '4-accept-form');
      await page.getByRole('button', {name: 'Confirmer l’acceptation', exact: true}).click();
      await page.locator('#toast', {hasText: 'Connaissance acceptée'}).waitFor();
      if (!(await detail.evaluate(element => element.open))) { await title.click(); await detail.locator('.detail-title').waitFor(); }
      await page.locator('#detail .detail-top .status', {hasText: 'Acceptée'}).waitFor();
      out.checks.accepted_through_ui = true;
      await scan(page);
      await shot(page, '5-accepted');
      lap('accepted');
    } else {
      await title.waitFor();
      await scan(page);
      for (const view of ['overview', 'entries', 'timeline', 'graph', 'handoff', 'import', 'capture']) {
        await page.locator(`[data-view="${view}"]`).click();
        await page.waitForTimeout(400);
        await scan(page);
        if (['overview', 'handoff', 'capture'].includes(view)) await shot(page, `view-${view}`, {fullPage: true});
      }
      await page.locator('[data-view="entries"]').click();
      await title.click();
      await page.locator('#detail .detail-title').waitFor();
      out.checks.accepted_sheet_status = await page.locator('#detail .detail-top .status').innerText();
      await scan(page);
      await shot(page, 'accepted-sheet');
      lap('scanned');
    }
    out.ok = out.leaks === 0;
    finish(out.ok ? 0 : 1);
  } catch (error) {
    out.error = String(error.message || error).split('\n')[0].slice(0, 240);
    try { out.last_screen = path.join(config.shots, `${config.prefix}-failure.png`); await (browser.contexts()[0]?.pages()[0]?.screenshot({path: out.last_screen})); } catch { /* best effort */ }
    finish(1);
  } finally {
    await browser.close().catch(() => {});
  }
})();
