# Revue d'architecture indépendante — cadrage Filigree V2

Date : 2026-10-17. Rôle : relecteur architecture (n'a pas rédigé le document). Statut : revue de document, aucune exécution de code.

**Périmètre.** [v2-vision-cadrage.md](../architecture/v2-vision-cadrage.md) confronté à `AGENTS.md`, ADR-0001, ADR-0002 (rév. 3), `README.md` et au code V1 (`capture.py`, `store.py`, `native_index.py`, `tap_source.py`, `server.py`). Lu : sections 1 à 12 du cadrage ; code consulté par extraits (verrous, `scan_once`, `locate_project`, `_resolve_native_uncached`, `NativeIndex`, jeton HTTP). Les points [O]/[C] du cadrage sur les formats Codex et Claude Desktop n'ont pas été re-vérifiés ici.

**Verdict.** Orientation saine (un seul processus, Markdown canonique, SQLite comme index, collecteurs isolés). Le cadrage n'est pas acceptable tel quel comme base d'ADR-0003 : 3 points bloquants (journal ni jetable ni scopé par projet, canal hook sans authentification, règle « répertoire git commun » fausse pour les clones et exploitable) et plusieurs vides de spécification sur la concurrence et la reprise après crash.

Légende : **bloquant** = à corriger avant ADR-0003 ; **majeur** = à trancher avant le lot concerné ; **mineur** = précision. « Différé » = écart assumé ou prévu par un lot ultérieur, pas un défaut.

## 1. Défauts (à corriger dans le cadrage)

| ID | Gravité | Section | Constat | Recommandation |
| --- | --- | --- | --- | --- |
| A-01 | bloquant | §7, §8, ADR-0001 | Le journal SQLite est décrit « local, reconstructible » et comme « index », mais les sources sont purgées (Claude 30 j, Codex compressé à 7 j, §5) et `detail_ref` pointe vers des sources qui disparaissent. Il contiendra donc des données qu'on ne peut pas rejouer. ADR-0001 exige « tout index ultérieur doit être jetable ». Le cadrage invoque le déclencheur de réexamen d'ADR-0001 sans constater que la condition « jetable » n'est plus tenue. | Dire explicitement que le journal est une **seconde source de données non reconstructible** (donc sauvegarde, export, versionnage de schéma, purge documentée), ou le rendre jetable en ne gardant que des curseurs et des propositions. Réviser ADR-0001 nommément dans ADR-0003. Définir le sort d'un `detail_ref` devenu orphelin. |
| A-02 | bloquant | §6, §7 | Le journal est global au démon, alors que l'invariant d'AGENTS.md dit « la mémoire d'un vrai projet appartient à son dossier local ». Le cadrage ne dit pas où vit la base ni comment suivent déplacement, suppression, export d'un projet. Pire : des événements non rattachés (« pending ») avec `summary` ≤ 280 car. seraient stockés alors qu'ADR-0002 §7 impose des attentes « clés seulement, sans texte ». C'est un recul de confidentialité non déclaré. | Trancher : base par projet dans le dossier mémoire du projet (cohérent avec l'invariant) ou base globale avec cascade de suppression/export par `project_id`. Les événements sans projet ne portent **aucun** texte (clé, compteurs, motif). Écrire ce changement comme révision d'ADR-0002 §7 si on le garde. |
| A-03 | bloquant | §4 B, §8, §10 | Les hooks « POST loopback » vers l'API de Filigree : le serveur V1 protège ses écritures par un jeton aléatoire **par processus** servi à la page (`server.py`), impossible à graver dans la config d'un agent, et un démon permanent a besoin d'un port stable. Sans secret durable, tout processus local (ou page web par rebinding/CSRF) peut forger des événements « preuve forte » (`cwd`, `session_id`, `transcript_path`) et donc injecter dans n'importe quel projet. Le niveau « preuve forte » attribué à B suppose un canal authentifié. | Port fixe ou fichier de découverte, secret durable de 256 bits dans un fichier lisible par l'utilisateur seulement, vérification Host/Origin conservée. Un hook ne **crée jamais** un rattachement : il réveille le collecteur, et la preuve reste lue dans le store de l'agent. Valider `transcript_path` contre les racines connues (pas de lecture de chemin arbitraire). |
| A-04 | bloquant | §6 règle 2 | « Répertoire git commun (…) les clones jumeaux d'un même dépôt rejoignent ainsi le même projet » est faux : deux clones ont deux répertoires `.git` distincts ; seuls les worktrees partagent le common dir. De plus, le gitdir/commondir est lu sur un `.git` fichier contrôlé par le contenu du dossier : un dépôt non fiable peut pointer vers le `.git` d'un autre projet et se fusionner avec lui (mélange de projets). Sous-modules : common dir dans `.git/modules/…` du parent, donc fusion non voulue avec le parent. | Retirer « clones jumeaux ». Accepter un worktree seulement si le lien est **réciproque** (`.git` → `gitdir`, et `gitdir/commondir` + `gitdir` pointent en retour sur ce dossier) et si le common dir appartient à un projet enregistré. Traiter sous-modules et dépôts nus comme « pas de fusion ». Lire ces fichiers directement (pas de sous-processus `git` par session dans un démon Windows ; le dossier de worktree peut déjà être supprimé à l'ingestion). |
| A-05 | majeur | §6 règles 1, 3, §5 | Clé de session `<client>:<id>` : ne distingue pas un sous-agent de sa mère si le transcript sidechain Claude réutilise le `sessionId` parent (marqué [?]), ni une reprise/fork (`--resume`, `codex resume`) qui recopie l'historique d'une session dans une autre. Risques : fusion d'agents, doublons massifs du journal. La règle 3 ne dit pas ce qui prime quand le `cwd` d'un sous-agent (worktree isolé) diffère de celui de sa mère : hérite-t-il du projet ? | Clé = `(client, session_id, agent_id/thread_id)`. `event_id` dérivé de l'identifiant natif de ligne (uuid/index source), pas de la session, pour absorber forks et reprises. Le lien de parenté ne confère **jamais** un projet : le sous-agent est rattaché par sa propre preuve ; désaccord avec la mère → attente + relation signalée. |
| A-06 | majeur | §6 règle 1, §5 | Une session peut changer de `cwd` (`CwdChanged`, `cd`, worktree créé en cours de route). La règle parle d'« un `cwd` associé exactement à cet identifiant » ; la V1 exige que **tous** les `cwd` d'un identifiant mènent au même projet (`ambiguous_cwd` sinon). La granularité n'est pas définie en V2 : par session ou par événement ? Un rattachement par session fige un événement dans le mauvais projet ; par événement, une session se disperse. De plus Codex `threads.cwd` et le `cwd` de `session_meta` peuvent diverger. | Définir : projet = fonction de la session (V1, sûr) ; événements dont le `cwd` local sort du projet sont conservés dans la session avec drapeau `outside_project`, sans copie dans l'autre projet. Désaccord entre deux sources de preuve d'une même session → attente, jamais « le plus direct l'emporte ». |
| A-07 | majeur | §6, §10, D4, F12 | Incohérence interne : §10 limite la reprise injectée aux connaissances **acceptées** ; D4 recommande « acceptées + activité non revue ». AGENTS.md : « Source text is untrusted data ». Les résumés d'activité issus d'une session (donc d'un contenu potentiellement hostile) relayés vers un autre agent forment un canal d'injection inter-sessions. Les outils MCP « sessions en cours » ne précisent pas leur portée : un agent du projet A pourrait lire l'activité de B. | Fixer D4 sur « acceptées seulement » en V2.2 ; activité non revue uniquement sur demande explicite, balisée comme donnée. Chaque outil MCP est restreint au projet résolu depuis le `cwd` de l'appelant (preuve de l'appelant, pas paramètre libre). |
| A-08 | majeur | §2 F11, ADR-0002 §1 | ADR-0002 a `auto_create=true` : tout `cwd` d'agent (même un dossier jetable) devient un projet. Sur un démon permanent qui lit tous les agents, cela crée des projets pour chaque dossier d'essai. F11 mentionne « dossiers autorisés/exclus » sans fixer la politique par défaut. | Décider opt-in (liste de racines autorisées choisies dans `setup`) ou opt-out, et le dire. Par défaut hors liste : session visible dans « Couverture » mais non ingérée. |
| A-09 | majeur | §8 | « Un seul démon » est contradictoire avec « le `serve` actuel avec son thread de capture, durci » : fermer l'interface tuerait la capture, ou deux `serve` se disputent le `ProcessLock`. Rôles non définis pour le démon, `filigree serve` (UI), les processus MCP stdio (un par client) et le CLI, tous écrivains potentiels du Markdown (verrou de workspace, délai d'attente 15 s). | Démon headless propriétaire de la capture et du journal ; `serve`/MCP/CLI sont clients (API loopback) ou lecteurs seuls du journal. Un seul écrivain SQLite par construction. Spécifier ce qui se passe si le démon est absent (MCP en lecture directe du Markdown, journal absent signalé). |
| A-10 | majeur | §7, §8 | Pas de protocole de reprise entre les deux stores. V1 est sûr parce que `import_events` est idempotent par URI puis l'état avance. V2 ajoute SQLite (curseurs + journal) et une distillation qui écrit des propositions Markdown : ordre d'écriture, clé d'idempotence d'une fiche de session (session + version de distillateur), fiche écrite deux fois si la session reprend après `session_end`. | Spécifier : curseur avancé dans la **même transaction** SQLite que les événements ; propositions dérivées avec URI déterministe `distill:<session_key>:<vN>` ; une session rouverte produit une révision, pas un doublon ; test de crash entre les deux écritures. |
| A-11 | majeur | §8 budget | Le Markdown est lent à l'échelle (65 s pour 3 000 entrées, un écrivain sous verrou). La distillation et le Markdown dans le même processus peuvent tenir le verrou de workspace et affamer l'UI/MCP. Les « 1-2 s actives / 15-30 s au repos » en polling `stat` sur `~/.claude/projects/**` et `~/.codex/sessions/**/AAAA/MM/JJ` n'ont pas de plafond (V1 borne 100 fichiers retenus et `MAX_FILES`). | Lots courts (une proposition par transaction), distillation en file à basse priorité, jamais pendant que l'UI attend. Fixer plafonds de fichiers/dossiers par cycle et mesurer avant de promettre « CPU < 1 % ». |
| A-12 | majeur | §4 D, règle 4 | Rattachement processus → session « par variable d'environnement, `--resume <id>`, verrou ». Lire l'environnement d'un autre processus (PEB) est fragile (WoW64, droits, PID réutilisé). Un PID recyclé ou un terminal parent partagé (multiplexeur, VS Code) peut étiqueter la mauvaise session ; terminal ≠ session. | Garder D strictement décoratif (jamais un champ de preuve dans le journal), clé de l'instance = `(pid, create_time)` pour résister au recyclage, et ne pas utiliser `ppid`/console pour regrouper des sessions. |
| A-13 | mineur | §6 règle 1 | Normalisation des chemins non traitée : casse Windows, jonctions/liens symboliques, lecteurs `subst`, chemins WSL (`\\wsl$`, Codex lancé dans WSL écrit un `~/.codex` distinct hors des racines scannées), MSIX (`LocalCache` virtualisé). V1 canonise par `resolve(strict=True)` + `normcase`. | Réutiliser `canonical_folder` partout ; lister dans « Couverture » les racines non découvertes (WSL, autres comptes) au lieu de les ignorer. |
| A-14 | mineur | §7 | Horloges : `ts_source` vient de l'agent, `lastActivityAt` de l'application, `timestamp` de tap ; aucune règle de dérive (changement d'heure, sources dans le futur, fuseaux). Chronologie « triée par horodatage source » et « 15 dernières minutes » en dépendent. | Stocker `ts_source` **et** `ts_observed` (horloge monotone/locale du démon) ; trier par `(ts_source, source, ordre)` ; borner les dates futures ; ne jamais s'en servir comme preuve (invariant respecté). |
| A-15 | mineur | §10 | Rétention/purge : pas de règle quand la purge du journal croise des propositions acceptées (leurs `sources` pointent vers des événements purgés), ni pour `uninstall`/pause (que devient l'historique ?). | Les propositions embarquent leur extrait (ADR-0001) et ne dépendent jamais d'une ligne du journal. Documenter purge, pause, `uninstall` (données conservées ou supprimées, demandé à l'utilisateur). |
| A-16 | mineur | §3 | Schéma du journal : pas de version de schéma ni de politique de migration (« schema drift » côté Filigree, pas seulement côté sources). | `user_version` + migrations avant-seulement, refus de démarrer sur version plus récente, sauvegarde avant migration. |

## 2. Invariants V1 : préservés, révisés, ou non traités

| Invariant (AGENTS.md / ADR) | État dans le cadrage | Commentaire |
| --- | --- | --- |
| Mémoire attachée au dossier local, jamais par ressemblance | Préservé en principe | Voir A-02 (journal global) et A-04 (worktrees/`.git` forgés). |
| Texte source = donnée non fiable | Affaibli | A-07 (reprise « non revu », hooks). |
| Imports et capture = propositions, pas d'auto-approbation | Préservé | À préciser que les événements du journal ne sont pas des connaissances ; les propositions de distillation gardent `proposed`. |
| Historique et provenance conservés | Menacé | A-01, A-15 : rétention bornée du journal vs provenance des propositions. |
| Pas de `.runtime`, `.traces`, conversations réelles, secrets dans git | Partiel | Le journal « hors checkpoints » est affirmé (§10), pas spécifié (emplacement, `.gitignore` insuffisant selon ADR-0001). |
| Dépendances d'exécution minimales | Préservé avec réserve | Extras `psutil`, `watchdog`, `zstandard`, `uv`/`pipx` ; la fonctionnalité dégradée doit rester testée sans extras. `irm \| iex` contredit l'esprit de « ne pas exécuter une source non fiable » : proposer un artefact vérifiable (hash). |
| Pas de modification silencieuse de la config d'un agent | **Révisé explicitement** (D1, §8) | Honnête, mais AGENTS.md est un fichier de règles écrit par l'humain : la révision exige son accord et la modification d'AGENTS.md par lui, pas seulement une ADR (« no silent edits to project instruction files »). Idem tâche planifiée / LaunchAgent / systemd : modification de la configuration système, à lister dans le diff de `setup`. |
| Lecture seule des sources | Préservé | Attention : le hook `notify` et l'outil MCP poussent des données **vers** Filigree, ce qui est compatible ; l'app-server Codex `thread/list` lance un processus de l'éditeur, à ne pas faire sans consentement. |

## 3. Exactitude de l'analyse d'écart V1 (§9) vérifiée au code

| Affirmation du cadrage | Verdict | Détail |
| --- | --- | --- |
| `capture.py` 1 493 l., `store.py` 1 139 l. | Exact | wc : 1493 / 1139. |
| « `tap_source`, `native_index` et le repli sont imbriqués dans `capture.py` » (F3) | **Inexact** | `tap_source.py` (525 l.) et `native_index.py` (237 l.) sont déjà des modules séparés avec des fonctions pures (`probe`, `read_batch`, `decode_payload`, `native_ids`, `NativeIndex.lookup`). Ce qui est couplé, c'est l'orchestration dans la classe `Capture` : `_scan_tap`, `_scan_fallback`, `_place_record`, `link`, `pending`. Le chantier est de séparer **orchestration et résolution**, pas d'extraire les modules. |
| `native_index.py` : « Étendre » avec `state_5.sqlite` et `local_*.json` | **Mal calibré** | L'index V1 est un lecteur JSONL incrémental par décalage (`read_lines_ex`, `files` avec `ids`/`cwds` bornés, détection de réécriture). Une base SQLite et des JSON à document unique sont d'une autre nature (mtime/ligne, pas de décalage). Les ajouter dans la même classe élargit sa surface ; préférer de nouveaux collecteurs derrière le contrat F3, en gardant `NativeIndex` comme brique réutilisable. |
| `_git_root` / `project_for_path` comme point de départ F5 | Exact mais incomplet | `_git_root` teste `(.git).exists()` : un worktree (fichier `.git`) est donc déjà vu comme racine git distincte, et `auto_create` crée **un projet par worktree** hors dossier enregistré. C'est le comportement à corriger ; il n'est pas mentionné et il explique le besoin de la règle 2. `locate_project` n'applique que l'ancêtre enregistré. |
| « Balayage périodique toutes les 3 s » | Exact | `run_foreground(interval=3.0)`, index natif toutes les 30 s (`index_interval`). |
| « `ProcessLock`, un seul moniteur par dossier de données » | Exact | Verrou OS exclusif (`msvcrt`/`fcntl`), libéré à la mort du processus. Bonne base pour A-09. |
| « Isolation d'erreurs par collecteur (`_isolated`) » | Exact | `scan_once` isole tap / index / repli. Un collecteur lent bloque néanmoins le cycle (un seul fil, `self.mutex`) : prévoir un délai par collecteur. |
| « 3 000 entrées, environ 65 s d'import mesurés (README) » | Exact | README l. 162 ; mesure unique, une machine, sans SLA : le cadrage ne doit pas en tirer plus. |
| `store.py` « Garder, écrire moins souvent » | Exact | Verrou de workspace réentrant + journal de transaction ; ne supporte pas plusieurs gros écrivains (A-11). |
| `mcp.py` « lecture + proposition » | Non vérifié en détail | Cohérent avec ADR-0001. |

## 4. Règles de corrélation : cas à ajouter à la matrice de tests V2.1

| # | Cas | Attendu |
| --- | --- | --- |
| C-1 | Deux terminaux, deux projets, mêmes minutes, même agent | Aucune entrée croisée (déjà en V1, à rejouer sur le journal). |
| C-2 | Worktree supprimé avant l'ingestion | Attente, pas de projet créé ; pas de sous-processus `git` bloquant. |
| C-3 | `.git` d'un dépôt cloné pointant vers le gitdir d'un projet enregistré, sans lien retour | Refus de fusion (A-04). |
| C-4 | Sous-module d'un projet enregistré | Pas de fusion avec le parent. |
| C-5 | Reprise `--resume` / fork recopiant l'historique | Aucun doublon d'événement ; une seule fiche. |
| C-6 | Sous-agent dont le `cwd` est hors du projet de la mère | Rattaché par sa preuve ou en attente, jamais par héritage. |
| C-7 | Session qui change de `cwd` vers un autre projet enregistré | Reste dans le projet de départ, événement signalé `outside_project`. |
| C-8 | Hook forgé avec un `session_id` existant et un `cwd` d'un autre projet | Rejeté, ou ignoré car la preuve est relue du store de l'agent. |
| C-9 | PID recyclé avec un autre agent | Instance distincte (A-12). |
| C-10 | Deux comptes / `CLAUDE_CONFIG_DIR` multiples avec le même `session_id` | Clé incluant la racine source. |

## 5. Modes de défaillance non couverts

| Défaillance | Lacune | Voir |
| --- | --- | --- |
| Arrêt brutal entre SQLite et Markdown | Aucun protocole de reprise | A-10 |
| `serve`/MCP/CLI concurrents avec le démon | Rôles et verrou d'écriture indéfinis | A-09 |
| Dérive de schéma côté Filigree (journal) | Pas de `user_version` | A-16 |
| Dérive de schéma côté agents | Bien traitée (sondes, `unsupported_schema`) ; ajouter un test de fixture par version de chaque source | §10 |
| Horloge (retour en arrière, futur) | Non traité | A-14 |
| Purge rétention vs provenance | Non traité | A-15 |
| Base SQLite en WAL placée dans un dossier synchronisé (OneDrive, réseau) | Non traité : WAL non fiable sur système de fichiers distant, verrous non respectés | A-01 : imposer un emplacement local, avertir au `setup` |
| Disque plein / base verrouillée par un antivirus | Seulement le statut `locked` pour tap | Étendre aux écritures du journal |
| Démon arrêté longtemps puis redémarré (rattrapage) | Le « rattrapage historique » est cité (§5) sans conflit avec la ligne de base V1 (« nouvelles sessions seulement ») | À spécifier : le rattrapage reste une action explicite par consentement |

## 6. Périmètre différé (pas des défauts)

- Collecteurs exports ChatGPT/claude.ai, boîte de dépôt, MCP dans Claude Desktop (V2.3) ; distillation sémantique (D3) ; exécutable empaqueté et icône (V2.x) ; OTLP ; Codex cloud ; chat Desktop.
- L'absence de capture silencieuse des conversations « chat » est assumée (§5, D6) et cohérente avec les invariants.
- Conservation d'un modèle distant : hors périmètre tant que D3 n'est pas tranchée.

## 7. Points forts à conserver

Passif d'abord, preuve avant exhaustivité, rattachement jamais par timing, extras facultatifs, sondes de schéma visibles, séparation connaissances gouvernées / activité, découpage en lots avec critères de sortie mesurables (V2.1 « aucune fuite entre projets »), niveaux de preuve [D]/[O]/[C]/[?] dans le texte.

## 8. Suite recommandée

1. Corriger A-01 à A-04 dans le cadrage avant tout travail d'ADR-0003.
2. Trancher A-05 à A-10 dans ADR-0003 (clé de session, rôles des processus, protocole de reprise).
3. Mesurer avant d'annoncer des budgets (A-11) ; ajouter C-1 à C-10 aux tests du lot V2.1.
4. Demander l'accord de l'humain sur la révision de l'invariant de configuration d'agent (D1) en modifiant AGENTS.md lui-même, hors de l'agent.
