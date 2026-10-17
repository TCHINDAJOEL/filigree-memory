/* Filigree's local workbench. No remote assets, analytics or runtime dependencies. */
'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kinds = {decision:'Décision',hypothesis:'Hypothèse',observation:'Observation',constraint:'Contrainte',procedure:'Méthode',question:'Question',correction:'Recadrage'};
const statuses = {proposed:'À examiner',accepted:'Acceptée',rejected:'Écartée',superseded:'Remplacée'};
const relations = {supports:'appuie',contradicts:'contredit',supersedes:'remplace',relates_to:'est lié à',implements:'met en œuvre'};
const views = {overview:'Vue d’ensemble',entries:'Connaissances',timeline:'Chronologie',graph:'Graphe',handoff:'Reprise',activity:'Activité',import:'Importer',capture:'Capture'};
const state = {token:'',projects:[],project:null,entries:[],events:[],view:'overview',filters:{query:'',kind:'',status:''},handoff:'',request:0,capture:null,liveSig:'',switching:0,target:'',detailId:'',projectSig:'',diagnostics:{entries:[],events:[]},graph:{query:'',status:'',limit:48}};
// Backend messages that may still arrive in English or as raw technical text are shown in French.
const knownErrors = [[/^Entry changed|a changé|a été modifiée/i,'Cette connaissance a été modifiée entre-temps.'],[/^Workspace busy/i,'La mémoire est occupée. Réessayez dans quelques instants.'],[/^(Project|Entry) not found/i,'Projet ou connaissance introuvable. Rechargez la page.'],[/^name is required/i,'Le nom du projet est obligatoire.'],[/^Title must be one line/i,'Le titre doit tenir sur une seule ligne.'],[/^A superseded entry cannot be reactivated/i,'Une connaissance remplacée ne peut pas être réactivée : créez une nouvelle proposition.'],[/^Only an accepted entry may supersede/i,'Seule une connaissance acceptée peut en remplacer une autre.'],[/^Target is already superseded/i,'Cette connaissance est déjà remplacée.'],[/^Import exceeds/i,'L’import dépasse 5 Mo. Importez une trace plus petite.'],[/^events must be a list of at most/i,'Un import ne peut pas dépasser 1 000 enregistrements. Découpez la trace.'],[/^Duplicate relation/i,'Ce lien existe déjà.'],[/^An entry cannot reference itself/i,'Une connaissance ne peut pas être reliée à elle-même.'],[/^Relation target does not exist/i,'La connaissance reliée n’existe pas dans ce projet.']];
const looksTechnical = message => /Traceback|^\w*(Error|Exception)\b|<class |\bNone\b|^[\[{]/.test(message);
const looksEnglish = message => /\b(is|are|must|cannot|required|invalid|unknown|exceeds|only|each|already|failed|error)\b/i.test(message)&&!/[éèàçêôûîùœ’]/.test(message)&&!/\b(le|la|les|du|un|une|des|est|pas|dans|sur)\b/i.test(message);
function frenchMessage(message,status) {
  const known=knownErrors.find(([pattern])=>pattern.test(message));if(known)return known[1];
  if(looksTechnical(message)||looksEnglish(message))return status===404?'Projet ou connaissance introuvable. Rechargez la page.':status>=500?'Le serveur local a rencontré un problème. Réessayez dans un instant.':'Cette demande n’est pas valide. Vérifiez votre saisie puis réessayez.';
  return message;
}
const isRevisionConflict = error => error.status===409&&/modifiée entre-temps/.test(error.message);
const channels = {'http-ui':'interface locale',mcp:'MCP (proposition)',import:'import',capture:'capture automatique',local:'ligne de commande'};
const tapStates = {ok:'Connecté en lecture seule',missing:'Base claude-tap introuvable : aucune session tap n’a encore été créée.',locked:'Base occupée : nouvel essai automatique.',corrupt:'Base illisible : rien n’est lu.',unsupported_schema:'Version de base non prise en charge (schéma 4 requis) : rien n’est lu.',disabled:'Lecture claude-tap désactivée.',unknown:'État inconnu.'};
const pendingReasons = {no_native_id:'La trace ne porte aucun identifiant de session natif.',ambiguous_native_id:'Identifiants de session contradictoires dans la trace. Rien n’est deviné : seul votre choix explicite pour cette session peut la rattacher, et il est conservé comme choix, pas comme preuve.',mapping_conflict:'Deux rattachements explicites se contredisent : retirez-en un (filigree capture unlink).',unknown_native:'Identifiant absent des transcriptions locales (client non pris en charge, ou transcription pas encore écrite).',ambiguous_cwd:'Plusieurs dossiers possibles : rien n’est deviné.',ambiguous_native_session:'Plusieurs sessions natives portent cet identifiant.',cwd_missing:'Le dossier annoncé par la session n’existe plus.',cwd_invalid:'Le dossier annoncé n’est pas un chemin absolu.',cwd_refused:'Dossier refusé (racine, dossier personnel ou mémoire Filigree).',outside_roots:'Dossier hors des racines autorisées : rien n’est lu ni créé tant que vous ne le rattachez pas explicitement.',no_project:'Aucun projet pour ce dossier et création automatique désactivée.',native_index_off:'Index des transcriptions désactivé.',mapping_project_missing:'Le projet choisi n’existe plus.','mappé':'Rattachement demandé, en cours de traitement.'};
const captureFolderNotice = project => project.folder?`<p class="folder-line">Dossier du projet : <code>${escapeHTML(project.folder.path)}</code>${project.folder_state==='missing'?' <span class="folder-warning">Ce dossier est introuvable sur ce disque.</span>':''}</p>`:`<div class="callout unbound" role="note"><strong>Ce projet n’est rattaché à aucun dossier.</strong> La capture automatique ne peut pas lui attribuer de session tant qu’un dossier local existant n’est pas choisi. <button class="button secondary small" data-action="attach-folder">Rattacher un dossier</button></div>`;
let toastTimer;
function toast(message, error = false) { const el=$('#toast');el.textContent=message;el.className=`visible${error?' error':''}`;clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.className='',4500); }
// Every API call except the bootstrap carries the local key; a call started before the bootstrap answer waits for it instead of failing with a 403.
let bootstrapped;
async function api(path, options={}) {
  if(path!=='/api/bootstrap'&&!state.token&&bootstrapped)await bootstrapped.catch(()=>{});
  const headers = {'Accept':'application/json',...(options.body?{'Content-Type':'application/json'}:{}),...(path!=='/api/bootstrap'?{'X-Filigree-Token':state.token}:{}),...options.headers};
  let response;
  try { response=await fetch(path,{...options,headers,body:options.body?JSON.stringify(options.body):undefined}); }
  catch { throw new Error('Le serveur local ne répond pas. Vérifiez que Filigree est démarré, puis réessayez.'); }
  const type=response.headers.get('content-type')||'';
  const data=type.includes('application/json')?await response.json():await response.text();
  if(!response.ok){const raw=typeof data==='object'&&(data.error||data.message);const failure=new Error(raw?frenchMessage(String(raw),response.status):`La requête a échoué (${response.status}).`);failure.status=response.status;throw failure;}
  return data;
}
const projectPath = (suffix,id=state.project.id) => `/api/projects/${encodeURIComponent(id)}${suffix||''}`;
// While a project switch is in flight, state.project still describes the previous project: nothing may write to it.
const assertStable = (id) => {if(state.switching||!state.project||(id&&state.project.id!==id))throw new Error('Changement de projet en cours : réessayez dans un instant. Votre saisie est conservée.');};
const list = (value,key) => Array.isArray(value)?value:(value?.[key]||[]);
const date = value => {if(!value)return 'À l’instant';const d=new Date(value);return isNaN(d)?String(value):new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}).format(d);};
const badge = status => `<span class="status ${escapeHTML(status)}">${escapeHTML(statuses[status]||status)}</span>`;
const parseObject = text => {try{const value=JSON.parse(text);return value&&typeof value==='object'&&!Array.isArray(value)?value:null;}catch{return null;}};
function safeLink(uri) {try{const url=new URL(uri);return ['http:','https:'].includes(url.protocol)?url.href:null;}catch{return null;}}
// Imports and captures attach bookkeeping sources (fingerprint, timestamp, provenance): only real evidence is counted and shown as such.
function sourceParts(sources=[]) {
  const provenanceSource=sources.find(s=>s.label==='Provenance de capture'&&parseObject(s.excerpt));
  const bookkeeping=s=>s===provenanceSource||(s.label==='Original event timestamp'&&!s.uri)||/^import:sha256:/.test(s.uri||'');
  const evidence=sources.filter(s=>!bookkeeping(s));
  const technical=sources.filter(s=>bookkeeping(s)&&s!==provenanceSource);
  // A plain import whose only evidence is its own fingerprint keeps it as evidence.
  if(!evidence.length&&technical.length){const own=technical.find(s=>/^import:sha256:/.test(s.uri||''));if(own){evidence.push(own);technical.splice(technical.indexOf(own),1);}}
  return {evidence,technical,provenance:provenanceSource?parseObject(provenanceSource.excerpt):null,provenanceSource};
}
const clientName = provenance => provenance.native_source==='codex'?'Codex':provenance.native_source==='claude'?'Claude Code':'';
function sourceLabel(source,provenance) {
  // The import bookkeeping labels every captured entry "claude-tap", even native-transcript ones.
  if(provenance?.collector==='native-fallback'&&source.label==='claude-tap')return `Transcription locale ${clientName(provenance)}`.trim();
  return source.label||'Source';
}
function provenanceMarkup(p) {
  const native=p.collector==='native-fallback';
  const rows=[['Origine',native?`Transcription locale ${clientName(p)}`.trim():'Trace claude-tap (capture automatique)'],['Rattachement',p.link==='explicit'?'Choisi par vous pour cette session':'Reconnu grâce au dossier de la session'],['Dossier de la session',p.cwd],['Dossier du projet choisi',p.target_folder],['Fichier de transcription',p.native_file],['Session',p.native_id||p.tap_session_id]].filter(([,value])=>value);
  return `<div class="source-card provenance"><strong>Provenance de la capture</strong><dl class="git-info">${rows.map(([name,value])=>`<dt>${escapeHTML(name)}</dt><dd>${escapeHTML(value)}</dd>`).join('')}</dl><p class="form-help">Ces identifiants sont des déclarations de l’outil d’origine, non authentifiées.</p></div>`;
}
function sourcesMarkup(sources,none) {
  const {evidence,technical,provenance,provenanceSource}=sourceParts(sources);
  const card=s=>`<div class="source-card"><strong>${escapeHTML(sourceLabel(s,provenance))}</strong>${s.excerpt?`<blockquote>${escapeHTML(s.excerpt)}</blockquote>`:''}${s.uri?(safeLink(s.uri)?`<a href="${escapeHTML(safeLink(s.uri))}" target="_blank" rel="noopener noreferrer">${escapeHTML(s.uri)}</a>`:`<p class="source-ref">Référence : ${escapeHTML(s.uri)}</p>`):''}</div>`;
  const raw=[...technical,...(provenanceSource?[provenanceSource]:[])];
  return (evidence.map(card).join('')||`<p class="no-source">${none}</p>`)+(provenance?provenanceMarkup(provenance):'')+(raw.length?`<details class="technical"><summary>Données techniques</summary>${raw.map(s=>`<p class="form-help">${escapeHTML(s.label)}</p><pre class="technical-data" tabindex="0">${escapeHTML(s.excerpt||s.uri||'')}</pre>`).join('')}</details>`:'');
}
const options = (values, selected, empty) => `${empty?`<option value="">${escapeHTML(empty)}</option>`:''}${Object.entries(values).map(([k,v])=>`<option value="${escapeHTML(k)}" ${k===selected?'selected':''}>${escapeHTML(v)}</option>`).join('')}`;
function shell() {
  const shown=state.switching?state.target:state.project?.id;
  $('#project-select').innerHTML=state.projects.length?state.projects.map(p=>`<option value="${escapeHTML(p.id)}" ${p.id===shown?'selected':''}>${escapeHTML(p.name)}${p.folder?'':' (sans dossier)'}</option>`).join(''):'<option value="">Aucun projet</option>';
  $('#project-name').textContent=state.project?.name||'Votre espace';
  $('#view-name').textContent=views[state.view];
  document.title=`${views[state.view]}${state.project?` — ${state.project.name}`:''} — Filigree`;
  $('#nav-count').textContent=state.entries.length;
  $('#footer-count').textContent=state.project?`${state.entries.length} connaissance${state.entries.length>1?'s':''} dans ce projet`:'Votre première page reste à écrire';
  const idle=!!state.project&&!state.switching;
  $('#add-entry').disabled=!idle;$('#export').disabled=!idle;$('#git-open').disabled=!idle;
  $$('.nav-item').forEach(el=>{el.classList.toggle('active',el.dataset.view===state.view);if(el.dataset.view===state.view)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
}
// Quarantined files are left out of every list: say so, instead of letting the memory look complete.
function paintDiagnostics() {
  const d=state.diagnostics,box=$('#diagnostics');if(!box)return;
  const rows=[...d.entries.map(x=>['Connaissance',x]),...d.events.map(x=>['Événement',x])];
  box.innerHTML=rows.length?`<div class="callout diagnostics" role="alert"><strong>${rows.length} fichier${rows.length>1?'s':''} de mémoire illisible${rows.length>1?'s':''} : non affiché${rows.length>1?'s':''}.</strong> Rien n’a été modifié ni supprimé ; ce que vous voyez peut être incomplet.<ul>${rows.map(([kind,x])=>`<li>${kind} <code>${escapeHTML(x.file)}</code> : ${escapeHTML(x.problem)}</li>`).join('')}</ul></div>`:'';
}
async function loadDiagnostics(id) {
  try{const result=await api(`/api/projects/${encodeURIComponent(id)}/diagnostics`);if(state.project?.id===id){state.diagnostics={entries:list(result.entries),events:list(result.events)};paintDiagnostics();}}catch{}
}
async function refresh(projectId) {
  const seq=++state.request;
  // An explicit request is recorded before any await, so a background refresh that starts meanwhile cannot pick another project.
  if(projectId)state.target=projectId;
  const data=await api('/api/projects');state.projects=list(data,'projects');
  // state.target is the last project the user asked for, so a refresh that finishes mid-switch cannot revert it.
  const wanted=projectId||state.target||state.project?.id||localStorage.getItem('filigree.project');
  const project=state.projects.find(p=>p.id===wanted)||state.projects[0]||null;
  if(!project){state.project=null;state.target='';state.entries=[];state.events=[];shell();render();return;}
  state.target=project.id;
  const [details,entries,events]=await Promise.all([api(`/api/projects/${encodeURIComponent(project.id)}`),api(`/api/projects/${encodeURIComponent(project.id)}/entries`),api(`/api/projects/${encodeURIComponent(project.id)}/events`)]);
  if(seq!==state.request)return;
  if(state.project?.id!==(details.project||details).id){state.diagnostics={entries:[],events:[]};paintDiagnostics();}
  state.project=details.project||details;state.entries=list(entries,'entries');state.events=list(events,'events');state.liveSig=liveSignature(state.entries,state.events);localStorage.setItem('filigree.project',state.project.id);state.projectSig=projectSignature(state.projects);shell();render();refreshDetail();loadDiagnostics(state.project.id);
}
const projectSignature = projects => JSON.stringify(projects.map(p=>[p.id,p.name,!!p.folder,!!p.demo]));
// An open detail sheet always describes the stored entry, never the version it was opened with.
function refreshDetail() {
  if(!$('#detail').open||!state.detailId)return;
  if(state.entries.some(e=>e.id===state.detailId)){const box=$('#detail');const top=box.scrollTop;detail(state.detailId);box.scrollTop=top;}
  else $('#detail').close();
}
const liveSignature = (entries,events) => `${entries.length}|${entries.reduce((m,e)=>String(e.updated_at)>m?String(e.updated_at):m,'')}|${events.length}`;
function go(view) { if(!views[view])view='overview';state.view=view;location.hash=view;clearTimeout(toastTimer);$('#toast').className='';shell();render(); }
function intro(title,description,extra='') {return `<div class="page-intro"><div><h1>${escapeHTML(title)}</h1><p>${escapeHTML(description)}</p></div>${extra}</div>`;}
function empty(title,description,action='') {return `<div class="empty-state"><div class="empty-icon" aria-hidden="true">⌁</div><h2>${escapeHTML(title)}</h2><p>${escapeHTML(description)}</p>${action}</div>`;}
function row(entry) {
  return `<article class="knowledge-row"><div class="row-heading"><button class="entry-title" data-entry="${escapeHTML(entry.id)}">${escapeHTML(entry.title)}</button>${badge(entry.status)}</div><p class="entry-excerpt">${escapeHTML(entry.body)}</p><div class="entry-meta"><span class="kind-label">${escapeHTML(kinds[entry.kind]||entry.kind)}</span><span title="Nom déclaré, non authentifié">↳ Déclaré : ${escapeHTML(entry.agent||'Humain')}</span><span>${sourceParts(entry.sources||[]).evidence.length} source${sourceParts(entry.sources||[]).evidence.length>1?'s':''}</span>${(entry.tags||[]).slice(0,3).map(t=>`<span class="tag">${escapeHTML(t)}</span>`).join('')}<span>${escapeHTML(date(entry.updated_at||entry.created_at))}</span></div></article>`;
}
function timelineEvents() {return [...state.events].sort((a,b)=>String(b.at||b.created_at||b.timestamp||'').localeCompare(String(a.at||a.created_at||a.timestamp||'')));}
function eventMarkup(event) {
  const entry=state.entries.find(e=>e.id===(event.entry_id||event.entity_id||event.entry_ids?.[0]));
  const type=event.type||event.action||'modification';
  const titles={'entry.created':'Connaissance ajoutée','entry.updated':'Connaissance révisée','import.completed':'Traces importées','events.imported':'Traces importées',created:'Connaissance ajoutée',entry_created:'Connaissance ajoutée',updated:'Connaissance mise à jour',entry_updated:'Connaissance mise à jour',imported:'Trace importée',project_created:'Projet créé',status_changed:'Statut modifié',reviewed:'Connaissance examinée'};
  const title=event.title||entry?.title||titles[type]||type;
  const status=event.status||event.after?.status;
  return `<div class="timeline-item"><time>${escapeHTML(date(event.at||event.created_at||event.timestamp))}</time>${entry?`<button class="entry-title" data-entry="${escapeHTML(entry.id)}">${escapeHTML(title)}</button>`:`<strong>${escapeHTML(title)}</strong>`}<p>${escapeHTML(titles[type]||type)}${event.agent?` · déclaré par ${escapeHTML(event.agent)}`:''}${event.channel?` · canal : ${escapeHTML(channels[event.channel]||event.channel)}`:''}${status?` · ${escapeHTML(statuses[status]||status)}`:''}${(event.revision||event.revisions?.[entry?.id])?` · révision ${escapeHTML(event.revision||event.revisions?.[entry?.id])}`:''}${event.entry_ids?.length>1?` · ${event.entry_ids.length} connaissances concernées`:''}</p>${event.reason?`<blockquote class="event-reason">${escapeHTML(event.reason)}</blockquote>`:''}</div>`;
}
function overview() {
  const accepted=state.entries.filter(e=>e.status==='accepted'), pending=state.entries.filter(e=>e.status==='proposed'), links=state.entries.reduce((n,e)=>n+(e.relations||[]).length,0);
  const recent=[...state.entries].sort((a,b)=>String(b.updated_at||b.created_at).localeCompare(String(a.updated_at||a.created_at))).slice(0,5);
  const emblem='<div class="intro-emblem" aria-hidden="true"><svg viewBox="0 0 60 60"><path d="M12 48V15h35M12 29h27M25 48V29M25 40h22M39 29V15"/><circle cx="12" cy="15" r="4"/><circle cx="25" cy="29" r="4"/><circle cx="47" cy="40" r="4"/><circle cx="39" cy="15" r="4"/></svg></div>';
  return intro('Gardez le fil de vos idées.',state.project.description||'Ce qui a été décidé, ce qui reste ouvert, et le chemin parcouru pour en arriver là.',emblem)+captureFolderNotice(state.project)+
    `<div class="overview-stats"><div class="stat"><strong>${state.entries.length}</strong><span>Connaissances<br>conservées</span></div><div class="stat"><strong class="green">${accepted.length}</strong><span>Connaissances<br>acceptées</span></div><div class="stat"><strong class="amber">${pending.length}</strong><span>Propositions<br>à examiner</span></div><div class="stat"><strong class="purple">${links}</strong><span>Liens entre<br>les idées</span></div></div>`+
    `<div class="overview-layout"><div><section><div class="section-heading"><h2>La mémoire en mouvement</h2><button class="text-button" data-go="entries">Tout consulter</button></div>${recent.length?`<div class="knowledge-list">${recent.map(row).join('')}</div>`:empty('Un projet, une première trace.','Une intention, une décision ou une question : commencez par ce qui compte.', '<button class="button primary" data-action="add">Ajouter une connaissance</button>')}</section><section class="mini-timeline"><div class="section-heading"><h2>Le fil des changements</h2><button class="text-button" data-go="timeline">Voir l’histoire</button></div><div class="timeline-list">${timelineEvents().slice(0,3).map(eventMarkup).join('')||'<p class="muted">Les prochaines évolutions apparaîtront ici.</p>'}</div></section></div><aside><section class="review-card"><h2>Un regard humain</h2><p>${pending.length?'Ces propositions attendent votre lecture.':'Toutes les propositions ont été examinées.'}</p>${pending.slice(0,3).map(e=>`<div class="review-item"><button class="entry-title" data-entry="${escapeHTML(e.id)}">${escapeHTML(e.title)}</button><p>${escapeHTML(e.agent||'Humain')} · ${escapeHTML(kinds[e.kind]||e.kind)}</p><div class="review-actions"><button class="button secondary" data-entry="${escapeHTML(e.id)}">Examiner</button><button class="button accept" data-accept="${escapeHTML(e.id)}">Accepter</button></div></div>`).join('')}${pending.length>3?'<button class="text-button" data-action="pending">Voir toutes les propositions</button>':''}</section><section class="guide-card"><span class="guide-icon" aria-hidden="true">⇄</span><h3>Le prochain agent partira d’ici.</h3><p>Transmettez le contexte utile, les décisions actuelles et les questions ouvertes. Chaque connaissance garde sa source.</p><button class="text-button" data-go="handoff">Préparer une reprise</button></section></aside></div>`;
}
// Accents and case never matter when searching: "eleve" finds "Élève".
const fold = value => String(value??'').normalize('NFD').replace(/\p{M}/gu,'').toLocaleLowerCase('fr');
function filteredEntries() {const {query,kind,status}=state.filters;const needle=fold(query).trim();return state.entries.filter(e=>(!kind||e.kind===kind)&&(!status||e.status===status)&&(!needle||fold([e.title,e.body,e.agent,e.episode,...(e.tags||[])].join(' ')).includes(needle)));}
function entriesView() {return intro('Des idées, avec leur contexte.','Retrouvez une connaissance, examinez ses sources et suivez ses évolutions.')+`<div class="filters"><div class="search-wrap"><span aria-hidden="true">⌕</span><input id="search" type="search" aria-label="Rechercher dans les connaissances" placeholder="Rechercher une décision, une idée, un mot…" value="${escapeHTML(state.filters.query)}"></div><select id="kind-filter" aria-label="Filtrer par type">${options(kinds,state.filters.kind,'Tous les types')}</select><select id="status-filter" aria-label="Filtrer par statut">${options(statuses,state.filters.status,'Tous les statuts')}</select></div><div id="entries-results">${entryResults()}</div>`;}
function entryResults() {const filtered=filteredEntries();return `<p class="entry-count" role="status">${filtered.length} connaissance${filtered.length>1?'s':''}</p>${filtered.length?`<div class="knowledge-list">${filtered.map(row).join('')}</div>`:(state.filters.query.trim()||state.filters.kind||state.filters.status)?empty('Aucune connaissance à afficher.','Aucune connaissance ne correspond à ces filtres. Modifiez-les ou réinitialisez-les.','<button class="button secondary" data-action="reset-filters">Réinitialiser les filtres</button>'):empty('Aucune connaissance pour le moment.','Ajoutez une première connaissance, ou importez des traces.','<button class="button primary" data-action="add">Ajouter une connaissance</button>')}`;}
function importView() {return intro('Faites entrer votre histoire.','Importez des notes, une conversation ou des traces structurées. Vous gardez la main sur leur validation.')+`<div class="import-layout"><form id="import-form" class="surface"><div class="upload-zone"><label for="import-file">Choisir un fichier texte, Markdown, JSON ou JSONL</label><input id="import-file" type="file" accept=".txt,.md,.json,.jsonl,.ndjson,text/plain,application/json"></div><label class="form-field">Nom de la source<input name="source" value="Note importée" required placeholder="Ex. Session Claude du 15 octobre"></label><label class="form-field">Texte ou traces<textarea name="text" rows="13" required placeholder="Collez ici votre conversation, vos notes ou une exportation JSON…"></textarea></label><div id="import-error"></div><button class="button primary" type="submit">Importer les traces</button><div id="import-result"></div></form><aside class="import-note"><h3>Une trace n’est pas une décision.</h3><p>Une importation crée des propositions. Relisez-les avant de les accepter comme connaissances actuelles du projet.</p><h3>Des sources préservées</h3><p>Le texte d’origine reste attaché aux connaissances importées pour retrouver le contexte et vérifier les formulations.</p><h3>Avec vos agents</h3><p>Importez les traces disponibles de Claude Code, Codex ou d’un autre assistant. Aucune clé de modèle n’est nécessaire.</p><p>Une conversation décrit ce qui a été exprimé. Elle ne donne pas accès aux pensées internes d’un modèle.</p></aside></div>`;}
function render() {
  $('#main').setAttribute('aria-busy','false');
  // The capture view is repainted piece by piece: rebuilding it would erase what the user is typing in its forms.
  if(state.view==='capture'&&$('#capture-banner')){paintCapture();return;}
  if(!state.project&&state.view!=='capture'){$('#main').innerHTML=`<div class="welcome">${intro('Chaque projet a une histoire.','Gardez ses décisions, ses détours et ses raisons dans une mémoire que vous pouvez transmettre.')}${empty('Bienvenue dans Filigree.','Créez votre projet ou explorez un exemple : une proposition technique, un recadrage, puis une décision qui conserve le chemin parcouru.','<div class="empty-actions"><button class="button primary" data-action="project">Créer mon premier projet</button><button class="button secondary" data-action="demo">Explorer la démonstration</button></div>')}</div>`;return;}
  const content={overview,entries:entriesView,timeline:()=>intro('Comprendre le chemin parcouru.','Les idées changent. Retrouvez quand, comment et avec quelles sources.')+`<section class="timeline-full">${timelineEvents().map(eventMarkup).join('')||empty('Le fil commence ici.','Ajoutez une connaissance : chaque évolution sera conservée.')}</section>`,import:importView,capture:captureView};
  if(content[state.view]){$('#main').innerHTML=content[state.view]();if(state.view==='capture')loadCapture();return;}
  $('#main').innerHTML=`<div class="loading-state"><span class="spinner"></span>Chargement…</div>`;
  if(state.view==='graph')loadGraph();if(state.view==='handoff')loadHandoff();if(state.view==='activity')loadActivity();
}
function showModal(title,body,footer='',formId='') {const modal=$('#modal');$('#modal-content').innerHTML=`${formId?`<form id="${formId}">`:''}<div class="dialog-header"><h2 id="modal-title">${escapeHTML(title)}</h2><button class="close-button" type="button" data-close="modal" aria-label="Fermer">×</button></div><div class="dialog-body">${body}<div id="form-error"></div></div>${footer?`<div class="dialog-footer">${footer}</div>`:''}${formId?'</form>':''}`;if(!modal.open)modal.showModal();markClean();}
// A dialog form holds a draft: leaving it through Escape, the backdrop or Annuler must not lose typed work silently.
const draftOf = dialog => JSON.stringify($$('input,textarea,select',dialog).map(el=>el.type==='checkbox'?el.checked:el.value));
function markClean() {const modal=$('#modal');modal.dataset.clean=draftOf(modal);}
const isDirty = dialog => dialog.id==='modal'&&dialog.open&&dialog.dataset.clean!==undefined&&draftOf(dialog)!==dialog.dataset.clean;
function closeDialog(dialog) {if(isDirty(dialog)&&!confirm('Vous avez une saisie non enregistrée. L’abandonner ?'))return false;dialog.close();return true;}
async function reloadConflict(button) {
  const form=button.closest('form'),id=$('[name="id"]',form).value,review=form.getAttribute('id')==='review-form';
  button.disabled=true;
  try{
    await refresh();
    const current=state.entries.find(e=>e.id===id),box=$('#form-error');
    if(!current){box.innerHTML='<p class="form-error" role="alert">Cette connaissance n’existe plus. Copiez votre saisie si besoin, puis fermez ce formulaire.</p>';return;}
    $('[name="revision"]',form).value=current.revision;
    if(review&&current.status!=='proposed'){const submit=$('[type="submit"]',form);if(submit)submit.disabled=true;box.innerHTML=`<p class="form-error" role="alert">Cette proposition a déjà été examinée : elle est maintenant « ${escapeHTML(statuses[current.status]||current.status)} ». Fermez ce formulaire.</p>`;return;}
    box.innerHTML=`<div class="form-error current-version" role="alert"><p>Version actuelle chargée (révision ${escapeHTML(current.revision)}, ${escapeHTML(statuses[current.status]||current.status)}). Votre saisie est conservée : relisez-la, puis enregistrez de nouveau si elle reste pertinente.</p><blockquote><strong>${escapeHTML(current.title)}</strong><br>${escapeHTML(current.body)}</blockquote></div>`;
  }catch(error){$('#form-error').innerHTML=`<p class="form-error" role="alert">${escapeHTML(error.message)}</p>`;}
  finally{button.disabled=false;}
}
function attachForm(){showModal('Rattacher un dossier à ce projet',`<p class="form-help">Indiquez le dossier local où travaillent vos agents. Il doit exister et un dossier n’appartient qu’à un seul projet. Filigree ne modifie rien dans ce dossier.</p><label class="form-field">Dossier du projet<input name="folder" required placeholder="Chemin absolu, ex. C:\\Projets\\mon-application" autofocus></label>`,`<button type="button" class="button secondary" data-close="modal">Annuler</button><button class="button primary" type="submit">Rattacher le dossier</button>`,'attach-form');}
function projectForm(){showModal('Un nouvel espace pour vos idées',`<label class="form-field">Nom du projet<input name="name" required maxlength="120" placeholder="Ex. Mon application" autofocus></label><label class="form-field">Dossier du projet<input name="folder" required placeholder="Chemin absolu d’un dossier existant, ex. C:\\Projets\\mon-application"><span class="form-help">Les sessions d’agents lancées dans ce dossier (ou l’un de ses sous-dossiers) alimenteront ce projet.</span></label><label class="form-field">Intention du projet<textarea name="description" rows="4" placeholder="Que voulez-vous construire, et pour qui ?"></textarea></label>`,`<button type="button" class="button secondary" data-close="modal">Annuler</button><button class="button primary" type="submit">Créer le projet</button>`,'project-form');}
function sourceEditor(source={}) {
  return `<div class="source-editor"><div class="editor-item-heading"><strong>Source</strong><button class="text-button" type="button" data-action="remove-editor">Retirer</button></div><label class="form-field">Nom de la source<input class="source-label" value="${escapeHTML(source.label||'')}" placeholder="Ex. Conversation de cadrage"></label><label class="form-field">Extrait d’origine<textarea class="source-excerpt" rows="3" placeholder="Le passage qui soutient cette connaissance">${escapeHTML(source.excerpt||'')}</textarea></label><label class="form-field">Adresse ou référence (facultatif)<input class="source-uri" value="${escapeHTML(source.uri||'')}" placeholder="https://… ou chemin d’un document"></label></div>`;
}
function relationEditor(relation={},entryId='') {
  const targets=state.entries.filter(e=>e.id!==entryId);
  return `<div class="relation-editor"><select class="relation-type-input" aria-label="Type de relation">${options(relations,relation.type||'relates_to')}</select><select class="relation-target-input" aria-label="Connaissance reliée" required><option value="">Choisir une connaissance</option>${targets.map(e=>`<option value="${escapeHTML(e.id)}" ${e.id===relation.target?'selected':''}>${escapeHTML(e.title)}</option>`).join('')}</select><button class="close-button" type="button" data-action="remove-editor" aria-label="Retirer cette relation">×</button></div>`;
}
function entryForm(entry=null) {
  if(!state.project)return;
  const allowedStatuses=entry?.status==='superseded'?{superseded:statuses.superseded}:{proposed:statuses.proposed,accepted:statuses.accepted,rejected:statuses.rejected};
  showModal(entry?'Modifier la connaissance':'Ajouter une connaissance',`<input type="hidden" name="project_id" value="${escapeHTML(state.project.id)}"><input type="hidden" name="id" value="${escapeHTML(entry?.id||'')}"><input type="hidden" name="revision" value="${escapeHTML(entry?.revision||'')}"><label class="form-field">Titre<input name="title" required maxlength="240" value="${escapeHTML(entry?.title||'')}" placeholder="Une idée précise, en une phrase" autofocus></label><label class="form-field">Contenu et raisons<textarea name="body" required rows="5" placeholder="Que sait-on ? Pourquoi ? Quelles limites ou incertitudes ?">${escapeHTML(entry?.body||'')}</textarea></label><div class="form-grid"><label class="form-field">Type<select name="kind" aria-label="Type">${options(kinds,entry?.kind||'observation')}</select></label><label class="form-field">Statut<select name="status" aria-label="Statut">${options(allowedStatuses,entry?.status||'proposed')}</select></label><label class="form-field">Auteur ou agent (déclaré, non authentifié)<input name="agent" value="${escapeHTML(entry?.agent||'Humain')}" placeholder="Humain, Claude, Codex…"></label><label class="form-field">Épisode<input name="episode" value="${escapeHTML(entry?.episode||'')}" placeholder="Ex. Cadrage initial"></label></div><label class="form-field tags-field">Étiquettes<input name="tags" value="${escapeHTML((entry?.tags||[]).join(', '))}" placeholder="architecture, recherche, produit"><span class="form-help">Séparez les étiquettes par des virgules.</span></label>${entry?`<label class="form-field">Raison de cette révision (facultatif)<textarea name="reason" rows="2" maxlength="2000" placeholder="Expliquez ce qui a changé et pourquoi."></textarea></label>`:''}<details class="form-section" ${(entry?.sources||[]).length?'open':''}><summary>Sources et preuves</summary><div id="source-editors">${(entry?.sources||[]).map(sourceEditor).join('')}</div><button type="button" class="button secondary small" data-action="add-source">+ Ajouter une source</button></details><details class="form-section" ${(entry?.relations||[]).length?'open':''}><summary>Liens avec les autres connaissances</summary><div id="relation-editors">${(entry?.relations||[]).map(r=>relationEditor(r,entry?.id)).join('')}</div><button type="button" class="button secondary small" data-action="add-relation" ${state.entries.filter(e=>e.id!==entry?.id).length?'':'disabled'}>+ Relier une connaissance</button><p class="form-help">Le lien « remplace » exige une connaissance acceptée. La connaissance précédente devient alors « remplacée » ; son histoire est conservée.</p></details>`,`<button type="button" class="button secondary" data-close="modal">Annuler</button><button class="button primary" type="submit">${entry?'Enregistrer la révision':'Ajouter la connaissance'}</button>`,'entry-form');
}
const incomingVerbs = {supports:'est appuyée par',contradicts:'est contredite par',supersedes:'est remplacée par',relates_to:'est liée à',implements:'est mise en œuvre par'};
function detail(entryId) {
  const entry=state.entries.find(e=>e.id===entryId);if(!entry)return;
  state.detailId=entry.id;
  const incoming=state.entries.flatMap(other=>(other.relations||[]).filter(r=>r.target===entry.id).map(r=>({type:r.type,from:other})));
  const history=timelineEvents().filter(e=>(e.entry_id||e.entity_id)===entry.id||(e.entry_ids||[]).includes(entry.id));
  $('#detail-content').innerHTML=`<div class="dialog-header"><div><div class="detail-top">${badge(entry.status)}<span class="muted">${escapeHTML(kinds[entry.kind]||entry.kind)}</span></div><h2 id="detail-title" class="detail-title">${escapeHTML(entry.title)}</h2></div><button class="close-button" data-close="detail" aria-label="Fermer">×</button></div><div class="dialog-body"><div class="detail-meta"><span title="Nom déclaré, non authentifié">Déclaré par ${escapeHTML(entry.agent||'Humain')} (non authentifié)</span>${entry.channel?`<span>Canal : ${escapeHTML(channels[entry.channel]||entry.channel)}</span>`:''}<span>Révision ${escapeHTML(entry.revision||1)}</span><span>${escapeHTML(date(entry.updated_at||entry.created_at))}</span></div>${entry.episode?`<p class="form-help">Épisode : ${escapeHTML(entry.episode)}</p>`:''}<div class="detail-body-text">${escapeHTML(entry.body)}</div><div class="entry-meta">${(entry.tags||[]).map(t=>`<span class="tag">${escapeHTML(t)}</span>`).join('')}</div><div class="view-toolbar detail-actions"><button class="button secondary" data-edit="${escapeHTML(entry.id)}">Modifier</button>${entry.status==='accepted'?`<button class="button secondary" data-action="replace" data-target="${escapeHTML(entry.id)}">Remplacer</button>`:''}${entry.status==='proposed'?`<button class="button accept" data-accept="${escapeHTML(entry.id)}">Accepter</button><button class="button danger" data-reject="${escapeHTML(entry.id)}">Écarter</button>`:''}</div>${entry.status==='proposed'?'<p class="form-help">Seule une connaissance acceptée peut être remplacée : acceptez-la d’abord.</p>':''}<section class="detail-block"><h3>Sources et preuves</h3>${sourcesMarkup(entry.sources||[],'Aucune source attachée. Ajoutez-en une pour rendre cette connaissance vérifiable.')}</section><section class="detail-block"><h3>Relations</h3>${(entry.relations||[]).map(r=>{const target=state.entries.find(e=>e.id===r.target);return `<div class="relation-row"><span class="relation-type">${escapeHTML(relations[r.type]||r.type)}</span><button class="entry-title" data-entry="${escapeHTML(r.target)}">${escapeHTML(target?.title||'Connaissance introuvable')}</button></div>`;}).join('')}${incoming.map(r=>`<div class="relation-row incoming"><button class="entry-title" data-entry="${escapeHTML(r.from.id)}">${escapeHTML(r.from.title)}</button><span class="relation-type">${escapeHTML(incomingVerbs[r.type]||r.type)} cette connaissance</span></div>`).join('')}${(entry.relations||[]).length||incoming.length?'':'<p class="muted">Cette connaissance n’est pas encore reliée.</p>'}</section><section class="detail-block"><h3>Historique des révisions</h3><div id="revision-snapshots" data-entry-id="${escapeHTML(entry.id)}"><p class="muted">Chargement des versions conservées…</p></div><h4 class="events-heading">Événements du projet</h4><div class="revision-list">${history.map(eventMarkup).join('')||`<p>Créée le ${escapeHTML(date(entry.created_at))}.</p>`}</div><p class="form-help">Identifiant : <code>${escapeHTML(entry.id)}</code></p></section></div>`;
  if(!$('#detail').open)$('#detail').showModal();
  loadHistory(entry.id);
}
async function loadHistory(entryId) {
  const projectId=state.project.id;
  try {
    const result=await api(`/api/projects/${encodeURIComponent(projectId)}/entries/${encodeURIComponent(entryId)}/history`);
    const box=$('#revision-snapshots');
    if(!box||box.dataset.entryId!==entryId||state.project.id!==projectId)return;
    const snapshots=list(result,'history');
    box.innerHTML=snapshots.length?snapshots.map(snapshot=>`<details class="revision-snapshot"><summary>Révision ${escapeHTML(snapshot.revision)} ${badge(snapshot.status)}<time>${escapeHTML(date(snapshot.updated_at||snapshot.created_at))}</time></summary><h4>${escapeHTML(snapshot.title)}</h4><div class="snapshot-body">${escapeHTML(snapshot.body)}</div><h4>Sources de cette révision</h4>${sourcesMarkup(snapshot.sources||[],'Aucune source attachée à cette révision.')}</details>`).join(''):'<p class="muted">Aucune version conservée disponible.</p>';
  }catch(error){const box=$('#revision-snapshots');if(box?.dataset.entryId===entryId)box.innerHTML=`<p class="form-error" role="alert">${escapeHTML(error.message)}</p>`;}
}
function reviewForm(id,status) {
  const entry=state.entries.find(e=>e.id===id);if(!entry)return;
  const accept=status==='accepted';
  showModal(accept?'Accepter cette connaissance':'Écarter cette proposition',`<input type="hidden" name="project_id" value="${escapeHTML(state.project.id)}"><input type="hidden" name="id" value="${escapeHTML(id)}"><input type="hidden" name="status" value="${escapeHTML(status)}"><input type="hidden" name="revision" value="${escapeHTML(entry.revision)}"><p class="review-subject">${escapeHTML(entry.title)}</p><p class="form-help">${accept?'Accepter signifie retenir cette connaissance pour le projet. Cela ne constitue pas une preuve indépendante.':'La proposition restera consultable dans l’histoire du projet.'}</p><label class="form-field review-reason">Raison de cette décision (facultatif)<textarea name="reason" rows="4" maxlength="2000" placeholder="Conservez le pourquoi de votre choix." autofocus></textarea></label>`,`<button type="button" class="button secondary" data-close="modal">Annuler</button><button class="button ${accept?'accept':'danger'}" type="submit">${accept?'Confirmer l’acceptation':'Confirmer l’écart'}</button>`,'review-form');
}
async function review(id,status,reason,revision,pid) {
  await api(projectPath(`/entries/${encodeURIComponent(id)}`,pid),{method:'PATCH',body:{status,revision:Number(revision),reason}});
  $('#modal').close();await refresh();if($('#detail').open)detail(id);toast(status==='accepted'?'Connaissance acceptée.':'Proposition écartée. Son histoire est conservée.');
}
const edgeEnd = end => typeof end==='object'?end.id:end;
async function loadGraph() {
  try {const graph=await api(projectPath('/graph'));if(state.view!=='graph')return;state.graphData={nodes:list(graph,'nodes'),edges:graph.edges||[]};state.graph.limit=48;paintGraph(true);}catch(error){showViewError(error);}
}
// A large memory is shown in bounded pages, linked knowledge first, with a filter: hundreds of boxes in one picture help nobody.
function paintGraph(full) {
  {const {nodes:everything,edges:everyEdge}=state.graphData,g=state.graph,needle=fold(g.query).trim();
    const linked=new Set(everyEdge.flatMap(e=>[edgeEnd(e.source),edgeEnd(e.target)]));
    const matching=everything.filter(n=>(!g.status||n.status===g.status)&&(!needle||fold(`${n.title||n.label||''} ${n.kind||''}`).includes(needle)));
    const nodes=[...matching.filter(n=>linked.has(n.id)),...matching.filter(n=>!linked.has(n.id))].slice(0,g.limit);
    const shownIds=new Set(nodes.map(n=>n.id)),edges=everyEdge.filter(e=>shownIds.has(edgeEnd(e.source))&&shownIds.has(edgeEnd(e.target)));
    const cols=nodes.length>12?4:Math.max(2,Math.ceil(Math.sqrt(nodes.length))),width=Math.max(780,cols*265),height=Math.max(470,Math.ceil(nodes.length/cols)*170+80);
    const positions=new Map(nodes.map((n,i)=>[n.id,{x:50+(i%cols)*265,y:55+Math.floor(i/cols)*170}]));
    const edgeSVG=edges.map(e=>{const a=positions.get(typeof e.source==='object'?e.source.id:e.source),b=positions.get(typeof e.target==='object'?e.target.id:e.target);if(!a||!b)return '';const x1=a.x+110,y1=a.y+42,x2=b.x+110,y2=b.y+42;return `<path class="graph-line ${escapeHTML(e.type)}" d="M${x1},${y1} C${x1},${(y1+y2)/2+45} ${x2},${(y1+y2)/2+45} ${x2},${y2}" marker-end="url(#arrow)"/><text class="graph-edge-label" x="${(x1+x2)/2}" y="${(y1+y2)/2+20}" text-anchor="middle">${escapeHTML(relations[e.type]||e.type)}</text>`;}).join('');
    const nodeSVG=nodes.map(n=>{const p=positions.get(n.id),title=n.title||n.label||n.id;const lines=title.match(/.{1,28}(?:\s|$)|.{1,28}/g)||[title];return `<g class="graph-node" transform="translate(${p.x} ${p.y})" tabindex="0" role="button" aria-label="${escapeHTML(title)}" data-entry="${escapeHTML(n.id)}"><rect width="220" height="89" rx="8"/><text x="15" y="20" class="node-kind">${escapeHTML(kinds[n.kind]||n.kind||'Connaissance')}</text><text x="15" y="42">${escapeHTML(lines[0]?.trim())}</text><text x="15" y="58">${escapeHTML((lines[1]||'').trim().slice(0,28))}${lines.length>2?'…':''}</text><text x="15" y="77" class="node-status">${escapeHTML(statuses[n.status]||n.status||'')}</text></g>`;}).join('');
    const body=nodes.length?`<div class="graph-surface"><svg viewBox="0 0 ${width} ${height}" role="group" aria-label="Graphe des connaissances"><defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" fill="none" stroke="#b7a6dc"/></marker></defs>${edgeSVG}${nodeSVG}</svg></div><div class="graph-legend"><span>Relation entre connaissances</span><span class="contradicts">Contradiction à examiner</span><span role="status">${nodes.length} connaissance${nodes.length>1?'s':''} affichée${nodes.length>1?'s':''} sur ${everything.length}, ${edges.length} lien${edges.length>1?'s':''}</span></div>${matching.length>nodes.length?`<button class="button secondary" data-action="graph-more">Afficher ${Math.min(48,matching.length-nodes.length)} de plus (${matching.length-nodes.length} masquées)</button>`:''}<p class="form-help">Parcourez aussi les nœuds avec Tab, puis Entrée pour les ouvrir.</p>`:(everything.length?empty('Aucune connaissance ne correspond.','Modifiez le filtre du graphe.'):empty('Reliez votre première idée.','Ajoutez des connaissances puis leurs relations pour explorer le graphe.'));
    if(!full&&$('#graph-body')){$('#graph-body').innerHTML=body;return;}
    $('#main').innerHTML=intro('Les idées ne vivent pas seules.','Explorez ce qui appuie, contredit ou remplace une connaissance. Sélectionnez un nœud pour consulter ses sources.')+(everything.length?`<div class="filters graph-filters"><div class="search-wrap"><span aria-hidden="true">⌕</span><input id="graph-search" type="search" aria-label="Filtrer le graphe" placeholder="Filtrer les connaissances du graphe…" value="${escapeHTML(g.query)}"></div><select id="graph-status" aria-label="Filtrer le graphe par statut">${options(statuses,g.status,'Tous les statuts')}</select></div>`:'')+`<div id="graph-body">${body}</div>`;
  }
}
async function loadHandoff(query='') {
  try {const data=await api(projectPath(`/handoff?query=${encodeURIComponent(query)}`));if(state.view!=='handoff')return;state.handoff=typeof data==='string'?data:(data.text||data.markdown||'');$('#main').innerHTML=intro('Reprendre, sans repartir de zéro.','Un contexte transmissible à un développeur, Claude, Codex ou votre prochain vous.')+`<div class="callout">Les connaissances acceptées et les propositions sont distinguées. Les alternatives écartées ou remplacées restent dans une section historique, explicitement non actuelle. Les références permettent de revenir aux sources.</div><form id="handoff-form" class="handoff-top"><input name="query" aria-label="Sujet de reprise" placeholder="Préciser un sujet (facultatif)" value="${escapeHTML(query)}"><button class="button secondary" type="submit">Préparer le contexte</button><button class="button primary" type="button" data-action="copy-handoff">Copier</button><button class="button secondary" type="button" data-action="download-handoff">Télécharger</button></form><pre class="code-output" tabindex="0">${escapeHTML(state.handoff)}</pre><p class="form-help">Relisez ce contexte avant de le transmettre à un service externe : il peut contenir des informations de votre projet.</p>`;}catch(error){showViewError(error);}
}
const activityKinds = {user_prompt:'Demande',assistant_text:'Réponse',tool_call:'Outil',tool_result:'Résultat',file_change:'Fichier modifié',command:'Commande',test_result:'Tests',error:'Erreur',commit:'Commit',session_start:'Début de session',session_end:'Fin de session'};
const shortKey = key => String(key||'').split(':').pop().slice(0,8);
async function loadActivity() {
  try {
    const data=await api(projectPath('/activity?limit=200'));if(state.view!=='activity')return;
    const active=data.active.length?`<ul class="activity-list">${data.active.map(s=>`<li><strong>${escapeHTML(s.client)}</strong> · session ${escapeHTML(shortKey(s.session_key))} · ${escapeHTML(s.event_count)} événement(s) · dernière activité ${escapeHTML(s.last_ts||'?')}</li>`).join('')}</ul>`:'<p class="muted">Aucune session active dans les 15 dernières minutes.</p>';
    const overlaps=data.overlaps.length?`<div class="callout warning" role="status"><strong>Chevauchement possible.</strong> ${data.overlaps.map(o=>`<code>${escapeHTML(o.file)}</code> (${o.sessions.length} sessions)`).join(', ')}</div>`:'';
    const rows=data.events.map(e=>`<li class="activity-event${e.outside_project?' outside':''}"><span class="activity-kind kind-${escapeHTML(e.kind)}">${escapeHTML(activityKinds[e.kind]||e.kind)}</span><span class="activity-summary">${escapeHTML(e.summary)}${e.files.length?` <span class="muted">· ${e.files.slice(0,3).map(f=>escapeHTML(f.split(/[\\/]/).pop())).join(', ')}</span>`:''}</span><span class="activity-meta">${escapeHTML(e.client)} · ${escapeHTML(shortKey(e.session_key))} · ${escapeHTML((e.ts_source||e.ts_observed||'').replace('T',' ').slice(0,16))}</span></li>`).join('');
    $('#main').innerHTML=intro('Ce que vos agents ont fait, en clair.','Le journal local observe les sessions Claude Code et Codex de ce projet. Ce sont des indices non revus : les fiches de session arrivent dans Connaissances comme propositions.')+
      `<div class="callout">${escapeHTML(data.note)} Les lignes de commande ne sont jamais conservées : seul le nom du programme l’est.</div>${overlaps}`+
      `<div class="overview-stats"><div class="stat"><strong>${escapeHTML(data.stats.events)}</strong><span>Événements<br>journalisés</span></div><div class="stat"><strong>${escapeHTML(data.stats.sessions)}</strong><span>Sessions<br>observées</span></div><div class="stat"><strong class="green">${escapeHTML(data.active.length)}</strong><span>Sessions<br>actives</span></div></div>`+
      `<section class="surface"><h2>Sessions actives</h2>${active}</section>`+
      `<section><div class="section-heading"><h2>Activité récente</h2><button class="text-button" data-action="reload-activity">Actualiser</button></div>${rows?`<ul class="activity-feed">${rows}</ul>`:empty('Aucune activité journalisée.','Lancez l’agent (« filigree agent ») puis travaillez avec Claude Code ou Codex dans le dossier du projet : les nouvelles sessions apparaîtront ici. L’historique antérieur n’est pas rattrapé.')}</section>`;
  } catch(error) {showViewError(error);}
}
function captureView() {
  return intro('Capture automatique, liée à vos dossiers.','Filigree observe en lecture seule les traces claude-tap et les transcriptions locales Claude/Codex, et ne retient que ce qui est rattaché à un dossier de projet sans ambiguïté.')+`<div id="capture-banner" role="status"></div><div class="capture-grid"><section class="surface capture-card" id="capture-controls" aria-label="Contrôles de capture"></section><section class="surface capture-card" id="capture-sources" aria-label="Sources de capture"></section></div><section class="surface capture-card" id="capture-pending" aria-label="Sessions non rattachées"></section><form id="exclude-form" class="surface capture-card"><h3>Exclure un dossier</h3><p class="form-help">Les sessions lancées dans un dossier exclu ne sont jamais capturées.</p><div class="inline-form"><label class="form-field grow">Dossier à exclure<input name="folder" required placeholder="Chemin absolu d’un dossier existant"></label><button class="button secondary" type="submit">Exclure ce dossier</button></div><div id="exclude-error"></div><div id="capture-excluded"></div></form><p class="form-help capture-limits">Le moniteur doit être actif (serveur Filigree démarré, ou <code>filigree capture start --background</code>). Il lit les traces claude-tap et, pour un client lancé directement, les transcriptions locales de Claude Code ou de Codex (quelques secondes à une minute de délai, uniquement les lignes complètes) ; il n’intercepte aucune application, et Claude Desktop ou Claude sur le web ne sont pas couverts. Les identifiants lus sont des déclarations, pas une authentification.</p>`;
}
function setIfChanged(selector, html) { const el=$(selector);if(!el||el.dataset.sig===html)return false;el.dataset.sig=html;el.innerHTML=html;return true; }
function paintCapture() {
  const c=state.capture;if(!c||state.view!=='capture'||!$('#capture-banner'))return;
  const mode=c.settings_error?'error':c.disabled_by_server?'off':!c.enabled?'off':c.paused_all?'paused':c.running?'on':'idle';
  const external=c.disabled_by_server&&c.external_monitor_running;
  const label={error:'Réglages invalides : capture désactivée',off:external?'Capture désactivée pour ce serveur — un moniteur externe tourne sur cette mémoire':'Capture désactivée',paused:'Capture en pause',on:'Capture active',idle:'Moniteur arrêté : rien n’est capturé'}[mode];
  setIfChanged('#capture-banner',`<div class="capture-state ${mode}"><span class="capture-light" aria-hidden="true"></span><strong>${escapeHTML(label)}</strong>${c.settings_error?`<span>${escapeHTML(c.settings_error)}</span>`:''}</div>`);
  const project=state.project, projectPaused=project&&(c.paused||[]).includes(project.id);
  if(c.disabled_by_server)setIfChanged('#capture-controls',`<h3>Contrôles</h3><p class="form-help">La capture est indisponible : ce serveur a été lancé sans capture (--no-capture). Relancez-le sans cette option pour l’activer.</p>${external?'<p class="form-help external-monitor">Un moniteur lancé par un autre processus utilise la même mémoire et continue de capturer. Ce serveur ne le pilote pas, mais peut lui demander de s’arrêter.</p><div class="button-row"><button class="button secondary" data-capture="stop">Arrêter le moniteur externe</button></div>':''}`);
  else setIfChanged('#capture-controls',`<h3>Contrôles</h3><div class="button-row">${c.enabled?'<button class="button secondary" data-capture="disable">Désactiver la capture</button>':'<button class="button primary" data-capture="enable">Activer la capture</button>'}${c.paused_all?'<button class="button primary" data-capture="resume">Reprendre</button>':'<button class="button secondary" data-capture="pause"'+(c.enabled?'':' disabled title="La capture est désactivée : rien à suspendre."')+'>Suspendre</button>'}${c.running?'<button class="button secondary" data-capture="stop">Arrêter le moniteur</button>':'<button class="button primary" data-capture="start">Démarrer le moniteur</button>'}</div>${project?`<div class="button-row">${projectPaused?`<button class="button primary" data-capture="resume-project">Reprendre ce projet</button>`:`<button class="button secondary" data-capture="pause-project">Mettre ce projet en pause</button>`}</div>`:''}<p class="form-help">Une pause ou une désactivation n’est jamais rattrapée : ce qui se passe pendant ce temps n’est pas capturé.</p>${project?captureFolderNotice(project):''}`);
  const counters=c.counters||{}, skipped=Object.values(c.skipped||{}).reduce((a,b)=>a+b,0), malformed=Object.values(c.malformed||{}).reduce((a,b)=>a+b,0);
  setIfChanged('#capture-sources',`<h3>Source claude-tap</h3><p class="tap-state ${escapeHTML(c.tap?.capability||'unknown')}">${escapeHTML(tapStates[c.tap?.capability]||tapStates.unknown)}</p><dl class="git-info"><dt>Base</dt><dd class="path">${escapeHTML(c.tap?.path||'—')}</dd><dt>Sessions vues</dt><dd>${escapeHTML(c.tap?.sessions??0)}</dd><dt>Importées</dt><dd id="capture-imported">${escapeHTML(counters.imported||0)}</dd><dt>Doublons absorbés</dt><dd>${escapeHTML(counters.duplicates||0)}</dd><dt>Ignorées</dt><dd>${skipped}</dd><dt>Illisibles</dt><dd>${malformed}</dd><dt>Réécrites / supprimées en amont</dt><dd>${escapeHTML(counters.rewritten||0)} / ${escapeHTML(counters.deleted_upstream||0)}</dd><dt>Repli natif</dt><dd>${c.native?.fallback?'Activé (provenance « transcription native »)':'Désactivé'}</dd></dl>${(c.notices||[]).slice(-3).map(n=>`<p class="form-help">${escapeHTML(date(n.at))} — ${escapeHTML(n.detail||n.code)}</p>`).join('')}`);
  const pending=c.pending||[], signature=JSON.stringify([pending,state.projects.map(p=>[p.id,p.name,!!p.demo])]);
  if($('#capture-pending').dataset.sig!==signature){
    const keep={};$$('#capture-pending select').forEach(s=>keep[s.dataset.key]=s.value);
    const choices=state.projects.filter(p=>!p.demo);
    $('#capture-pending').dataset.sig=signature;
    $('#capture-pending').innerHTML=`<h3>Sessions non rattachées <span class="nav-count">${pending.length}</span></h3><p class="form-help">Aucun contenu n’est conservé pour ces sessions. Choisissez un projet : seule l’activité postérieure à la mise en route de la capture est importée, sauf si vous demandez l’historique.</p>${pending.length?pending.map(p=>`<div class="pending-item" data-key="${escapeHTML(p.key)}"><div><strong class="pending-key">${escapeHTML(p.key.length>40?p.key.slice(0,38)+'…':p.key)}</strong><span class="muted"> · ${escapeHTML(p.client||'client inconnu')} · ${p.stalled?'transcription native retenue : lue à nouveau dès que la session est résolue':`${escapeHTML(p.count)} enregistrement${p.count>1?'s':''}${p.overflow?'+':''} · ${escapeHTML(date(p.first_ts))} → ${escapeHTML(date(p.last_ts))}`}</span><p class="form-help">${escapeHTML(pendingReasons[p.reason]||p.reason)}</p></div>${p.key.startsWith('file:')?'<div class="pending-actions"><span class="muted">Aucun identifiant de session : rattachement impossible.</span></div>':`<div class="pending-actions"><select data-key="${escapeHTML(p.key)}" aria-label="Projet pour ${escapeHTML(p.key)}"><option value="">Choisir un projet</option>${choices.map(q=>`<option value="${escapeHTML(q.id)}" ${keep[p.key]===q.id?'selected':''}>${escapeHTML(q.name)}</option>`).join('')}</select>${p.stalled?'':`<label class="check"><input type="checkbox" data-history="${escapeHTML(p.key)}"> avec l’historique</label>`}<button class="button primary small" data-capture="link" data-key="${escapeHTML(p.key)}">Rattacher</button></div>`}</div>`).join(''):'<p class="muted no-pending">Aucune session en attente.</p>'}`;
  }
  setIfChanged('#capture-excluded',(c.exclude||[]).map(f=>`<div class="excluded-row"><code>${escapeHTML(f)}</code><button class="text-button" type="button" data-capture="include" data-folder="${escapeHTML(f)}">Réinclure</button></div>`).join(''));
}
function updatePill() {
  const pill=$('#capture-pill'),c=state.capture;if(!pill||!c)return;
  const mode=c.disabled_by_server&&c.external_monitor_running?'on':c.settings_error||!c.enabled?'off':c.paused_all?'paused':c.running?'on':'idle';
  pill.className=`capture-pill ${mode}`;pill.textContent={off:'Capture désactivée',paused:'Capture en pause',on:c.disabled_by_server?'Moniteur externe actif':'Capture active',idle:'Moniteur arrêté'}[mode]+((c.pending||[]).length?` · ${c.pending.length} en attente`:'');
}
async function loadCapture() {
  try{state.capture=await api('/api/capture');}catch(error){if(state.view==='capture'&&$('#capture-banner'))setIfChanged('#capture-banner',`<div class="capture-state error"><strong>État de la capture indisponible</strong><span>${escapeHTML(error.message)}</span></div>`);return;}
  updatePill();paintCapture();
}
async function captureAction(target) {
  const action=target.dataset.capture,body={action};
  if(action==='pause-project'||action==='resume-project'){try{assertStable();}catch(error){toast(error.message,true);return;}body.action=action.split('-')[0];body.project_id=state.project.id;}
  if(action==='include')body.folder=target.dataset.folder;
  if(action==='link'){const item=target.closest('.pending-item'),select=$('select',item);if(!select.value){toast('Choisissez d’abord un projet.',true);return;}body.key=target.dataset.key;body.project_id=select.value;body.import_history=!!$('input[type="checkbox"]',item)?.checked;}
  target.disabled=true;
  try{const result=await api('/api/capture',{method:'POST',body});state.capture=result.status;updatePill();paintCapture();toast(action==='link'?'Session rattachée. Seule l’activité postérieure à la ligne de base est importée.':'Capture mise à jour.');if(action==='link')await refresh();}
  catch(error){toast(error.message,true);}finally{target.disabled=false;}
}
// Automatic capture can create a project while the page is open: the selector learns about it, the selection and any draft stay as they are.
async function pollProjects() {
  const projects=list(await api('/api/projects'),'projects'),signature=projectSignature(projects);
  if(signature===state.projectSig)return;
  state.projects=projects;state.projectSig=signature;
  if(state.project){const current=projects.find(p=>p.id===state.project.id);if(current?.name)state.project.name=current.name;}
  if(!state.project&&!$('#modal').open&&!state.switching){await refresh();return;}
  shell();if(state.view==='capture')paintCapture();
}
async function liveTick() {
  if(document.hidden||state.switching)return;
  try{
    try{if(state.view==='capture')await loadCapture();else if(state.token){state.capture=await api('/api/capture');updatePill();}}catch{}
    await pollProjects();
    if(!state.project)return;
    const id=state.project.id;
    const [entries,events]=await Promise.all([api(`/api/projects/${encodeURIComponent(id)}/entries`),api(`/api/projects/${encodeURIComponent(id)}/events`)]);
    if(!state.project||state.project.id!==id)return;
    const nextEntries=list(entries,'entries'),nextEvents=list(events,'events'),signature=liveSignature(nextEntries,nextEvents);
    loadDiagnostics(id);
    if(signature===state.liveSig)return;
    state.liveSig=signature;state.entries=nextEntries;state.events=nextEvents;shell();
    // Never rebuild what the user may be typing in: dialogs and forms stay untouched.
    refreshDetail();
    if($('#modal').open)return;
    if(state.view==='entries'&&$('#entries-results'))$('#entries-results').innerHTML=entryResults();
    else if(['overview','timeline'].includes(state.view))render();
  }catch{}
}
function showViewError(error){$('#main').innerHTML=empty('Impossible de charger cette vue.',error.message,'<button class="button secondary" data-action="retry">Réessayer</button>');}
function download(text,name,type='text/markdown;charset=utf-8'){const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function exportProject(){const data=await api(projectPath('/export'));download(typeof data==='string'?data:(data.text||data.markdown||JSON.stringify(data,null,2)),`${state.project.name.replace(/[^\p{L}\p{N}_-]/gu,'-')}.md`);toast('Mémoire exportée.');}
async function gitDialog(){const data=await api(projectPath('/git'));showModal('Versionner la mémoire',`<p class="muted">Conservez un état du projet dans Git. Le dépôt de mémoire peut rester local ou être relié à votre propre dépôt distant.</p><dl class="git-info"><dt>Git</dt><dd>${data.available?'Disponible':'Non disponible sur cette machine'}</dd><dt>Dépôt</dt><dd>${data.initialized?'Initialisé':'Non initialisé'}</dd><dt>Branche</dt><dd>${escapeHTML(data.branch||'—')}</dd><dt>Modifications</dt><dd>${data.dirty?'À enregistrer':'Aucune modification détectée'}</dd><dt>Distant</dt><dd>${escapeHTML(data.remote||'Aucun distant configuré')}</dd></dl>${data.available?`<label class="form-field">Message du point de sauvegarde<input id="checkpoint-message" value="docs: update project memory"></label><div class="view-toolbar">${!data.initialized?'<button class="button secondary" data-git="init">Initialiser Git</button>':'<button class="button primary" data-git="checkpoint">Créer un point de sauvegarde</button>'}${data.initialized&&data.remote?'<button class="button secondary" data-git="push">Pousser vers le distant</button>':''}</div>`:'<p>Installez Git puis relancez Filigree pour activer cette fonction.</p>'}`);}
async function handleAction(event){
  const target=event.target.closest('button,[data-entry]');if(!target)return;
  if(target.matches('button[type="submit"]'))return;
  if(target.dataset.close){closeDialog($(`#${target.dataset.close}`));return;}
  if(target.dataset.go){go(target.dataset.go);return;}
  if(target.dataset.view){go(target.dataset.view);return;}
  if(target.dataset.entry){detail(target.dataset.entry);return;}
  if(target.dataset.edit){$('#detail').close();entryForm(state.entries.find(e=>e.id===target.dataset.edit));return;}
  const action=target.dataset.action;
  if(action==='graph-more'){state.graph.limit+=48;paintGraph();return;}
  if(action==='reload-conflict'){await reloadConflict(target);return;}
  if(action==='add-source'){$('#source-editors').insertAdjacentHTML('beforeend',sourceEditor());return;}
  if(action==='add-relation'){$('#relation-editors').insertAdjacentHTML('beforeend',relationEditor({},$('#entry-form [name="id"]').value));return;}
  if(action==='remove-editor'){target.closest('.source-editor,.relation-editor').remove();return;}
  if(action==='replace'){const old=state.entries.find(e=>e.id===target.dataset.target);$('#detail').close();entryForm();$('#entry-form [name="status"]').value='accepted';$('#entry-form [name="kind"]').value=old?.kind||'decision';$('#relation-editors').innerHTML=relationEditor({target:old.id,type:'supersedes'});$('#relation-editors').closest('details').open=true;markClean();return;}
  if(target.dataset.capture){await captureAction(target);return;}
  if(action==='attach-folder'){attachForm();return;}
  if(action==='project'||target.id==='new-project'){projectForm();return;}
  if(action==='add'||target.id==='add-entry'){entryForm();return;}
  if(action==='pending'){state.filters.status='proposed';go('entries');return;}
  if(action==='reset-filters'){state.filters={query:'',kind:'',status:''};render();return;}
  target.disabled=true;
  try {
    if(target.dataset.accept)reviewForm(target.dataset.accept,'accepted');
    else if(target.dataset.reject)reviewForm(target.dataset.reject,'rejected');
    else if(action==='demo'){const data=await api('/api/demo',{method:'POST',body:{}});await refresh(data.id||data.project?.id);toast('Le projet de démonstration est prêt.');}
    else if(action==='retry')await refresh();
    else if(action==='reload-activity')loadActivity();
    else if(action==='copy-handoff'){try{await navigator.clipboard.writeText(state.handoff);toast('Contexte de reprise copié.');}catch{toast('Copie indisponible. Utilisez Télécharger pour récupérer le contexte.',true);}}
    else if(action==='download-handoff')download(state.handoff,'filigree-reprise.md');
    else if(target.id==='export')await exportProject();
    else if(target.id==='git-open')await gitDialog();
    else if(target.dataset.git){assertStable();const result=await api(projectPath('/git'),{method:'POST',body:{action:target.dataset.git,message:$('#checkpoint-message')?.value||'docs: update project memory'}});toast(result.message||'Opération Git terminée.');await gitDialog();}
  }catch(error){toast(error.message,true);}finally{target.disabled=false;}
}
async function handleSubmit(event){
  const form=event.target;const formId=form.getAttribute('id');if(!['project-form','attach-form','exclude-form','entry-form','import-form','handoff-form','review-form'].includes(formId))return;event.preventDefault();const data=Object.fromEntries(new FormData(form));const submit=$('[type="submit"]',form),idleLabel=submit?.textContent;
  // Busy state: a disabled button that says what is happening, and no error or result left over from the previous attempt.
  if(submit){submit.disabled=true;submit.textContent=({'import-form':'Importation en cours…','handoff-form':'Préparation…','exclude-form':'Exclusion…','review-form':'Enregistrement…'})[formId]||'Enregistrement en cours…';}
  form.setAttribute('aria-busy','true');$$('#form-error,#import-error,#exclude-error,#import-result').forEach(box=>box.innerHTML='');
  // Project-bound writes target the project the form was opened for, never whatever the global state becomes.
  const pid=data.project_id||state.project?.id;
  try{
    if(['attach-form','entry-form','import-form','review-form'].includes(formId))assertStable(pid);
    if(formId==='project-form'){const created=await api('/api/projects',{method:'POST',body:{name:data.name.trim(),folder:data.folder.trim(),description:data.description.trim()}});$('#modal').close();state.filters={query:'',status:'',kind:''};state.view='overview';location.hash='overview';await refresh(created.id||created.project?.id);toast('Projet créé. Ajoutez votre première connaissance.');}
    else if(formId==='attach-form'){await api(projectPath('',pid),{method:'PATCH',body:{folder:data.folder.trim()}});$('#modal').close();await refresh();toast('Dossier rattaché au projet.');}
    else if(formId==='exclude-form'){
      const own=state.project?.folder?.path;
      if(own&&data.folder.trim().replace(/[\\/]+$/,'').toLowerCase()===own.replace(/[\\/]+$/,'').toLowerCase()&&!confirm('Ce dossier est celui du projet affiché : plus rien ne sera capturé pour ce projet. L’exclure quand même ?'))return;
      const result=await api('/api/capture',{method:'POST',body:{action:'exclude',folder:data.folder.trim()}});state.capture=result.status;form.reset();$('#exclude-error').innerHTML='';paintCapture();toast('Dossier exclu de la capture.');}
    else if(formId==='review-form')await review(data.id,data.status,data.reason.trim(),data.revision,pid);
    else if(formId==='entry-form'){
      const sources=$$('.source-editor',form).map(el=>({label:$('.source-label',el).value.trim(),excerpt:$('.source-excerpt',el).value.trim(),uri:$('.source-uri',el).value.trim()}));
      const links=$$('.relation-editor',form).map(el=>({target:$('.relation-target-input',el).value,type:$('.relation-type-input',el).value}));
      if(sources.some(s=>!s.label))throw new Error('Donnez un nom à chaque source.');
      if(links.some(r=>r.type==='supersedes')&&!['accepted','superseded'].includes(data.status))throw new Error('Acceptez cette connaissance pour qu’elle puisse en remplacer une autre.');
      const body={title:data.title.trim(),body:data.body.trim(),kind:data.kind,status:data.status,agent:data.agent.trim(),episode:data.episode.trim(),tags:data.tags.split(',').map(t=>t.trim()).filter(Boolean),sources,relations:links};
      if(data.id){body.revision=Number(data.revision);body.reason=data.reason?.trim()||'';}
      await api(projectPath(`/entries${data.id?'/'+encodeURIComponent(data.id):''}`,pid),{method:data.id?'PATCH':'POST',body});$('#modal').close();await refresh();
      // After an edit the sheet the user came from is shown again with what is now stored (new revision, new relations).
      if(data.id&&state.entries.some(e=>e.id===data.id))detail(data.id);
      toast(data.id?'Nouvelle révision enregistrée.':links.some(r=>r.type==='supersedes')?'Remplacement enregistré. L’ancienne connaissance est conservée dans l’historique.':'Connaissance ajoutée.');
    }
    else if(formId==='import-form'){
      const result=await api(projectPath('/import',pid),{method:'POST',body:{text:data.text,source:data.source,format:/\.(txt|md)$/i.test(data.source)||!data.text.trimStart().match(/^[\[{]/)?'text':'auto'}});
      const count=result.count??result.imported??result.entries?.length??result.created?.length;const duplicateCount=result.duplicates||0;
      await refresh();$('#import-result').innerHTML=`<div class="import-result">${escapeHTML(typeof count==='number'?`${count} connaissance${count>1?'s':''} importée${count>1?'s':''}.`:'Importation terminée.')} ${duplicateCount?`${duplicateCount} doublon(s) déjà présent(s).`:''}<br><button class="text-button" data-action="pending">Examiner les propositions</button></div>`;toast('Traces importées. Examinez les propositions.');
    }
    else if(formId==='handoff-form')await loadHandoff(data.query.trim());
  }catch(error){
    const errorBox=formId==='import-form'?$('#import-error'):formId==='exclude-form'?$('#exclude-error'):$('#form-error');
    // An edit or a review refused because the entry moved on: say so in French and offer to load the current version, keeping the draft.
    if(errorBox&&isRevisionConflict(error)&&['entry-form','review-form'].includes(formId))errorBox.innerHTML=`<div class="form-error" role="alert"><p>${escapeHTML(error.message)} Une autre version a été enregistrée pendant votre saisie (par vous dans un autre onglet, ou par une capture automatique). Votre saisie est conservée dans ce formulaire.</p><button type="button" class="button secondary small" data-action="reload-conflict">Charger la version actuelle</button></div>`;
    else if(errorBox)errorBox.innerHTML=`<p class="form-error" role="alert">${escapeHTML(error.message)}</p>`;else toast(error.message,true);
  }finally{form.removeAttribute('aria-busy');if(submit){submit.disabled=false;submit.textContent=idleLabel;}}
}
document.addEventListener('click',handleAction);
document.addEventListener('submit',handleSubmit);
document.addEventListener('input',event=>{
  if(event.target.id==='search'){state.filters.query=event.target.value;$('#entries-results').innerHTML=entryResults();}
  if(event.target.id==='graph-search'){state.graph.query=event.target.value;state.graph.limit=48;paintGraph();}
  if(event.target.closest('#import-form'))$('#import-error').innerHTML='';
});
document.addEventListener('change',async event=>{
  if(event.target.id==='graph-status'){state.graph.status=event.target.value;state.graph.limit=48;paintGraph();}
  if(event.target.id==='kind-filter'||event.target.id==='status-filter'){state.filters[event.target.id==='kind-filter'?'kind':'status']=event.target.value;$('#entries-results').innerHTML=entryResults();}
  if(event.target.id==='project-select'){
    const draft=state.view==='import'&&$('#import-form [name="text"]');
    // Switching rebuilds the import form: never discard typed text without asking, and never move it to another project silently.
    if(draft&&draft.value.trim()&&!confirm('Le texte saisi dans l’import sera perdu si vous changez de projet. Continuer ?')){event.target.value=state.project?.id||'';return;}
    state.switching++;state.target=event.target.value;shell();
    try{state.filters={query:'',status:'',kind:''};await refresh(event.target.value);}
    catch(error){state.target=state.project?.id||'';toast(error.message,true);}
    finally{state.switching--;shell();}
  }
  if(event.target.id==='import-file'){const file=event.target.files[0];if(!file)return;if(file.size>5*1024*1024){toast('Le fichier dépasse 5 Mo. Importez une trace plus petite.',true);return;}try{$('#import-form [name="text"]').value=await file.text();$('#import-form [name="source"]').value=file.name;}catch{toast('Ce fichier ne peut pas être lu.',true);}}
});
document.addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ')&&event.target.classList.contains('graph-node')){event.preventDefault();detail(event.target.dataset.entry);}});
window.addEventListener('hashchange',()=>{const view=location.hash.slice(1);if(views[view]&&view!==state.view){state.view=view;shell();render();}});
for(const dialog of $$('dialog'))dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)closeDialog(dialog);}});
// Escape asks first when the form holds a draft. The keydown is intercepted so that a second Escape cannot close the dialog behind the question.
document.addEventListener('keydown',event=>{if(event.key!=='Escape')return;const open=$$('dialog[open]').pop();if(open&&isDirty(open)){event.preventDefault();event.stopPropagation();closeDialog(open);}},true);
document.addEventListener('cancel',event=>{if(isDirty(event.target)){event.preventDefault();closeDialog(event.target);}},true);
$('#detail').addEventListener('close',()=>{state.detailId='';$('#detail-content').innerHTML='';});
setInterval(liveTick,6000);
bootstrapped=api('/api/bootstrap');(async()=>{try{const data=await bootstrapped;state.token=data.token||data.csrf_token||'';$('#version').textContent=data.version?`v${data.version}`:'';const view=location.hash.slice(1);if(views[view])state.view=view;await refresh();loadCapture();}catch(error){$('#main').setAttribute('aria-busy','false');showViewError(error);}})();
