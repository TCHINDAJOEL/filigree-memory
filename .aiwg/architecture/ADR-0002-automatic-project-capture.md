# ADR-0002 — Capture automatique rattachée à un dossier de projet local

Date : 16 octobre 2026 (révision 2). Auteur : architecte (Opus). Statut : retenu pour implémentation (Sonnet) ; intégration et orchestration par Codex. Complète [ADR-0001](ADR-0001-local-portable-memory.md). S'appuie sur [l'étude du source claude-tap](tap-source-study.md), notée « Étude §n » ci-dessous.

**Révision 2, amendée par l'orchestrateur après clarification utilisateur :** claude-tap devient le **collecteur principal**. Les transcriptions natives servent de preuve de dossier et de collecteur pour les clients lancés directement. La création automatique est retenue dès qu'une session identifie exactement un dossier local valide. Voir [l'exigence confirmée](../requirements/automatic-capture.md), qui prévaut sur les restrictions du premier plan ci-dessous.

## Révision 3 — état implémenté (16 octobre 2026, suivi de l'implémentation)

Le corps ci-dessous est conservé comme décision d'origine. Là où il diffère, **cette section prévaut** (elle décrit le code, pas une intention) :

| Sujet (§ d'origine) | Implémenté |
| --- | --- |
| Repli natif désactivé par défaut (§5, §8) | **Activé par défaut** (`sources.native_fallback: true`) : une commande `claude` ou `codex` directe est le parcours principal. Il lit les nouvelles lignes complètes, avec un court délai de grâce, et se déduplique avec tap par un registre borné et expirant d'empreintes de contenu (15 min) par session native. Il ne s'arrête pas pour une session « vue dans tap » : chaque canal consomme les empreintes de l'autre. `capture fallback off` le désactive. |
| Conflit d'identifiants rejeté (§3.1) | Des identifiants contradictoires dans un record laissent la session en attente (`ambiguous_native_id`) ; **seul le choix explicite `tap:<session>`** la rattache, conservé comme choix (`link: explicit`, `target_folder`, identifiants annoncés), jamais comme preuve de dossier natif. Codex : `session_id` et `thread_id` sont tous deux lus. |
| Portée des rattachements (§3.2, §8) | Un rattachement `tap:ID` est enregistré avec l'identité de la base (`tap:ID@<db_key>`) et ne s'applique qu'à elle ; ceux d'une autre base restent stockés mais inactifs. Un rattachement par identifiant natif ne dépend pas de la base. À un changement de base, les clés en attente sont mises de côté dans `pending.quarantine-*.json` (clés seulement). |
| Perte au repli natif | Une ligne native dont la session n'est pas encore résolue (index en retard, dossier absent, plusieurs dossiers, projet absent avec `auto_create` désactivé) n'avance **pas** le décalage : le fichier est retenu à cette ligne (au plus 100 fichiers), exposé en attente sans texte, relu dans l'ordre à la résolution ou au rattachement explicite. Seules une pause ou une exclusion délibérées sont ignorées définitivement ; une pause ou une désactivation globale ne rattrape rien. |
| Index natif (§4) | Lecture bornée de 256 Kio en tête de fichier puis incrémentale ; une réécriture à longueur égale est détectée par la date de modification et abandonne l'ancienne correspondance de dossier. |
| Décodeur (§2) | Chaque référence indique et vérifie version, nature, empreinte et taille ; la taille d'un blob est bornée dans SQLite avant lecture. |
| Pensée cachée (§2) | Exclue dans les deux canaux : blocs `thinking`/`reasoning*`, canaux `analysis`, `reasoning`, etc. |
| `capture import-tap` (§6) | **Non implémenté** : l'historique d'une session se demande par `capture link … --import-history`. |
| Contrôle | Pause globale ou par projet, exclusion de dossier, verrou de processus exclusif, arrêt coopératif, démarrage Windows optionnel. L'interface offre les mêmes actions par l'API `POST /api/capture`. |

Éléments non établis : aucun essai avec un client réel n'est revendiqué par ce document ; l'essai manuel `scripts/verify_live_capture.py` concerne un seul échange Claude Code et ses résultats sont consignés dans `.aiwg/testing/verification.md`.

## Contexte
L'utilisateur exige qu'une mémoire soit rattachée à un vrai dossier local, que ce dossier désigne le même projet pour Claude et pour Codex, et que la capture parte des traces claude-tap avec un lien exact. Tap n'enregistre aucun `cwd` (Étude §6). Il faut donc prouver la chaîne **dossier → session native → session tap + record → entrée**, sans jamais rien deviner.

## Alternatives
| Option | Verdict |
| --- | --- |
| A. Hooks, injection de configuration, modification de CLAUDE.md/AGENTS.md | Rejetée : modification silencieuse des agents. |
| B. Lecture des transcriptions natives seule | Rétrogradée au rang de repli : ne passe pas par tap, alors que l'utilisateur l'exige. |
| C. Instancier `claude_tap.TraceStore` | Rejetée : la lecture peut migrer ou écrire la base (Étude §3). |
| **D. Adaptateur SQLite stdlib en lecture seule, corrélé aux transcriptions natives par identifiant exact** | **Retenue.** |

## Décision

### 1. Projet = dossier
`project.json` gagne `"folder": {"path", "key"}` et `"demo"`. Le dossier est canonisé par `store.canonical_folder` : `resolve(strict=True)`. On refuse une racine de lecteur, le dossier personnel, le dossier de données Filigree et un chemin non absolu. Un dossier appartient à un seul projet (`ConflictError`). `project_for_path` retient l'ancêtre enregistré le plus proche. `key = sha256(normcase(path))` : le **même dossier donne le même projet**, quel que soit le client. Les surfaces web/CLI `create --folder` et `PATCH folder` permettent aussi un rattachement explicite. **`auto_create=true` par défaut** : après correspondance native exacte, utiliser le projet enregistré le plus proche, sinon la racine Git la plus proche si identifiable, sinon le dossier de travail. Un identifiant ou dossier ambigu reste en attente.

### 2. Collecteur principal : `filigree/tap_source.py`
- **Chemin de la base** : `capture.json` `tap.db`, puis `CLOUDTAP_DB`, puis `$XDG_DATA_HOME/claude-tap/traces.sqlite3`, puis `~/.local/share/claude-tap/traces.sqlite3`. C'est l'ordre exact d'upstream (Étude §1), précédé de la surcharge Filigree.
- **Ouverture** : `sqlite3.connect(Path(p).as_uri() + "?mode=ro", uri=True, timeout=1)`, puis `PRAGMA query_only=ON`. Une connexion par cycle, fermée à la fin du cycle. Ne jamais importer `claude_tap`, ne jamais créer le dossier, ne jamais créer ni toucher au `.write.lock`. En lecture seule, SQLite peut créer `-shm` s'il manque. Ce point est documenté comme limite. Aucune autre écriture n'est permise.
- **Capacités** (`probe(db) -> dict`) : `missing` si le fichier est absent. `unsupported_schema` si `user_version != 4` ou si une colonne de l'Étude §2 manque (`PRAGMA table_info`). `locked` si l'erreur `database is locked` persiste. `corrupt` sur `sqlite3.DatabaseError`. Sinon `ok`. Tout état autre que `ok` : **aucune lecture des records**, et l'état apparaît dans le statut.
- **Lecture incrémentale** : `SELECT session_id, record_index, timestamp, payload_json FROM records WHERE session_id=? AND record_index>? ORDER BY record_index LIMIT 200`, pour chaque session de `SELECT id, client, started_at, updated_at, record_count FROM sessions`. Taille maximale de `payload_json` : 8 Mio. Au-delà, l'enregistrement est marqué `oversize`.
- **Décodeur borné** (`decode_payload(conn, session_id, text)`), conforme à l'Étude §4 :
  - Marqueur absent : l'enregistrement est brut.
  - Marqueur présent : `version == 1` et `encoding == "json-blob-ref"`, sinon `unsupported_record_version`.
  - Chaque `ref.path` doit appartenir aux quatre chemins fixes ou à `/request/body/{input|messages}/<entier>`. Sinon `unsupported_ref_path`.
  - Si `refs` est vide, balayer uniquement ces chemins.
  - Au plus 4 096 refs. Blob lu par `(session_id, hash, 'json')` : il doit exister, `sha256(payload_json.encode()) == hash` et `size_bytes == len(bytes) == ref.bytes`. Sinon `blob_missing` ou `blob_mismatch`.
  - Taille totale matérialisée : au plus 32 Mio. Cache par cycle.
  - Le nœud remplacé doit satisfaire `is_blob_ref` (exactement une clé).
  - Toute anomalie rejette **l'enregistrement entier**, sans remplacement partiel.
- **Extraction des identifiants natifs** (`native_ids(record) -> set[(kind, value)]`) : uniquement les champs de l'Étude §7. En-têtes lus sans tenir compte de la casse. `metadata.user_id` décodé seulement si c'est un objet JSON portant `session_id`. `x-codex-turn-metadata` est accepté en chaîne JSON ou en objet. `prompt_cache_key` **n'est pas utilisé**. Valeurs acceptées : chaîne de 1 à 128 caractères `[A-Za-z0-9_.:-]`.
- **Extraction du texte** : seulement le tour nouveau. Côté utilisateur : le dernier élément `role:user` de `request.body.messages` (blocs `text`) ou de `request.body.input` (`input_text`). Le bloc est retenu s'il est textuel et ne commence pas par `<environment_context>`, `<user_instructions>` ou `<system-reminder>`. Côté assistant : `response.body.content[type=text]` (Anthropic) ou `response.body.output[type=message, role=assistant].content[type=output_text]` (Responses). Le reste (`thinking`, `reasoning`, outils, réponses non 2xx, sondes `/models`) est compté dans `skipped`.

### 3. Chaîne de rattachement : déterministe et fermée en cas de doute
Pour chaque record tap décodé, `link(record)` parcourt les étapes dans l'ordre :
1. `ids = native_ids(record)`. S'il y a **plusieurs valeurs distinctes** dans un même record (par exemple un en-tête ≠ `metadata.session_id`), le record est rejeté (`ambiguous_native_id`).
2. **Rattachement explicite** : si `mappings.json` contient l'identifiant natif ou, à défaut, `tap:<tap_session_id>`, on utilise le projet indiqué (choix de l'utilisateur). Le choix est stocké localement dans `<data-dir>/.capture/mappings.json`.
3. **Preuve native** : on cherche l'identifiant dans l'index des transcriptions (§4) avec une égalité **exacte**. Si l'identifiant correspond à exactement une session native et que tous ses `cwd` canonisés donnent un seul projet, le record est lié avec la preuve `{native_source, native_session_id, native_file, cwd}`.
4. Si plusieurs sessions natives ou plusieurs `cwd`/projets correspondent : `ambiguous_cwd`, et le record est mis en attente.
5. Sinon (identifiant absent ou inconnu, `cwd` sans projet, dossier refusé) : le record est mis en **attente**, rattaché à sa clé (identifiant natif, ou `tap:<id>` sans identifiant).

**Interdits** : choisir la dernière session, se fier à la proximité de dates, déduire depuis `basename`, du texte libre, `prompt_cache_key` ou `capture.client`, ou chercher une sous-chaîne (comme `find_codex_app_session_row`).

### 4. Index des transcriptions natives (preuve de dossier)
`filigree/native_index.py` lit en lecture seule les racines de la révision 1 : `$CLAUDE_CONFIG_DIR|~/.claude/projects/**/*.jsonl` et `$CODEX_HOME|~/.codex/sessions/**/*.jsonl`. Il construit `native_session_id → {source, file, cwds:set}`.
- Claude : `sessionId` et `cwd` de chaque ligne.
- Codex : `session_meta.payload.id` et `payload.cwd` de la première ligne (≤ 64 Kio).

On lit uniquement les métadonnées : on ne garde aucun texte. La lecture est incrémentale par décalage, avec la même gestion de rotation qu'en révision 1. **Couverture réelle** : les clients qui écrivent ces fichiers (Claude Code CLI ou IDE, onglet Code de l'application de bureau, Codex CLI ou App). Ni Claude bureau ni Claude web n'est garanti. Une égalité entre l'identifiant de tap et l'identifiant natif qui ne se constate pas laisse l'entrée en attente, sans erreur silencieuse.

### 5. Collecteur de repli (optionnel, désactivé par défaut)
`capture.json` `sources.native_fallback: false`. Si l'option est activée, le texte est capturé depuis la transcription native, **seulement pour les sessions natives qu'aucun record tap n'a liées**, avec l'URI `native:<source>:<session>:<uuid|sha256(ligne)>`. Le filtrage est celui de la révision 1. Si une session native est ensuite vue dans tap, le repli s'arrête pour elle. Le statut affiche « repli natif » à part.

### 6. Nouvelles sessions seulement
Au premier scan, une **ligne de base** est enregistrée dans `state.json` : `tap.baseline = {session_id: max(record_index)}` pour toutes les sessions existantes, et `offset = size` pour les fichiers natifs. Une session tap déjà connue continue après son index de base ; une session nouvelle part de l'index 0. L'historique n'est jamais ingéré, sauf par `filigree capture link KEY PROJECT_ID --import-history` (explicite) ou `capture import-tap --session ID --project PID`.

### 7. Déduplication, réécriture, suppression
- Événement : `sources=[{"label": "claude-tap · <client> · <tap_session[:8]> #<record_index>", "uri": "tap:<tap_session_id>:<record_index>:<role>", "excerpt": texte[:4000]}]` et `provenance` (champ data) = `{tap_db_key: sha256(chemin résolu)[:16], tap_session_id, record_index, payload_sha256, native_id, link: "native"|"explicit", native_file, cwd}`. `episode = native_id or tap_session_id`. `agent` = `Claude Code` ou `Codex` d'après le type d'identifiant, à défaut `capture.client`. Cette valeur est descriptive : elle ne prouve pas qui est l'auteur.
- Le même message utilisateur répété dans l'historique n'est pas réimporté : on extrait seulement le dernier tour (§2). L'URI dépend du couple session+index, pas du contenu.
- Si `payload_sha256` diffère pour un index déjà ingéré (`replace_record_payloads`), il n'y a pas de réimport : on compte `rewritten`. Si la session disparaît, on compte `deleted_upstream` et la mémoire n'est pas touchée.
- Les records en attente sont stockés comme **clés seulement** (`pending.json` : clé, tap_session_id, liste d'index, client, premier/dernier horodatage, motif), **sans texte**. Après un rattachement explicite, seuls les index en attente postérieurs à la ligne de base sont relus depuis tap.
- Ordre de reprise après crash : `import_events` d'abord, état ensuite. Une relecture est absorbée par l'URI.

### 8. Exécution, contrôle, interface
Comme en révision 1 (§5-§6 : thread de `serve`, `capture run|start --background|stop`, verrou, tâche planifiée seulement à la demande), avec les ajouts suivants :
- `capture.json` : `{"enabled": true, "tap": {"enabled": true, "db": null}, "sources": {"native_index": true, "native_fallback": false}, "roots": {}, "exclude": [], "paused": []}`. Une valeur malformée désactive la capture.
- CLI : `capture pending`, `capture link KEY PROJECT_ID [--import-history]`, `capture unlink KEY`.
- HTTP : `GET /api/capture` inclut `tap: {path, capability, sessions, last_index}` et `pending`. `POST /api/capture {action: "link"|"unlink", key, project_id}` est protégé par jeton.
- Interface : un panneau « Sessions non rattachées » liste clé, client, nombre de records, plage de dates et motif, sans contenu, avec un sélecteur de projet. Le bandeau affiche la capacité de tap.

### 9. Lecture par les agents (inchangé)
Aucune injection automatique. `filigree mcp-config --client claude|codex` **affiche** l'extrait de configuration ; l'utilisateur l'installe lui-même. L'outil MCP `project_for_folder` est maintenu. Filigree ne modifie jamais les fichiers de configuration, CLAUDE.md ni AGENTS.md.

## Tâches pour Sonnet (dans l'ordre)
1. `store.py` : `canonical_folder`, `folder` et `demo` dans `create_project`, `attach_folder`, `project_for_path`, `import_events(tags=, provenance=)`.
2. `tap_source.py` : `resolve_db_path(settings, env)`, `probe`, `iter_new_records(conn, cursors)`, `decode_payload`, `native_ids`, `extract_turn`.
3. `native_index.py` : `NativeIndex.refresh(roots, state)`, `lookup(native_id) -> list`.
4. `capture.py` : `link`, ligne de base, curseurs, `pending.json`, `mappings.json`, `scan_once`, repli optionnel.
5. CLI, HTTP, interface et MCP du §8. README : section « Capture via claude-tap et limites ».

## Tests à écrire (fixtures synthétiques, stdlib, `tmp_path`)
Une fabrique `make_tap_db(path, sessions)` écrit à la main le DDL v4 de l'Étude §2, `user_version=4`, et des payloads compacts construits comme dans l'Étude §4. Elle n'importe pas `claude_tap`.
1. **Schéma** : la v4 est acceptée. Une v3, une v5 ou une colonne manquante donnent `unsupported_schema`, sans records lus.
2. **Internement** : un message de 512 octets ou plus est restitué à l'identique. Un hachage altéré, une taille fausse, un blob absent, un chemin hors liste, `version: 2` ou un nœud porteur d'une clé en trop rejettent l'enregistrement entier. Le cas `refs` vide utilise le repli de balayage.
3. **Lecture seule** : hachage de la base, du `-wal` et du mtime avant et après `scan_once`, identiques ; aucun `.write.lock` créé. Un écrivain concurrent (thread qui ajoute des records en WAL pendant le scan) donne des records ingérés une seule fois, sans erreur.
4. **Corrompu ou absent** : fichier inexistant (`missing`, dossier non créé), octets aléatoires (`corrupt`), base verrouillée en écriture exclusive (`locked`, puis reprise).
5. **Lien exact** : l'en-tête `X-Claude-Code-Session-Id=S1` et un JSONL Claude `sessionId=S1, cwd=A` donnent le projet A, avec une provenance complète.
6. **Rejet** : un en-tête et `metadata.user_id.session_id` différents donnent `ambiguous_native_id`. S1 présent dans deux fichiers natifs aux `cwd` de projets différents donne `ambiguous_cwd`. Un identifiant inconnu, un record sans identifiant ou un `cwd` sans projet donnent une mise en attente, sans écriture. Une session récente avec un `cwd` valide mais un identifiant différent n'est **pas** liée (test anti-proximité).
7. **Deux projets** : les sessions tap S1 (dossier A) et S2 (dossier B), entrelacées par horodatage, n'ont aucune entrée croisée. Claude S1 dans A et Codex `x-codex-turn-metadata.session_id=C1` (dans `session_meta` de A) arrivent dans le **même** projet.
8. **Ligne de base** : un premier scan n'ingère rien. Un record ajouté ensuite à une session existante est ingéré. Une nouvelle session est ingérée depuis l'index 1.
9. **Reprise et déduplication** : un crash simulé après `import_events` ne crée aucun doublon. Un redémarrage du processus non plus. Une réécriture du payload donne `rewritten` sans nouvel événement. Une session supprimée donne `deleted_upstream`.
10. **Rattachement explicite** : `capture link tap:<id> P` ingère seulement les index postérieurs à la ligne de base. Avec `--import-history`, l'historique est ingéré. `pending.json` ne contient aucun texte.
11. **Filtrage** : le raisonnement, les outils, `<environment_context>`, les réponses 4xx et `/v1/models` ne sont pas ingérés. Le dernier tour seulement est extrait d'un historique de 5 messages.
12. **Repli natif** : désactivé, il n'ingère rien. Activé, il n'ingère pas une session déjà liée par tap.
13. **Intégrité** : la configuration des agents, CLAUDE.md et AGENTS.md sont inchangés. Le scan ne fait aucun accès réseau (socket neutralisé).

## Conséquences
La capture passe par tap avec une provenance vérifiable record par record. Elle dépend de l'égalité constatée entre les identifiants tap et les identifiants natifs ; à défaut, l'utilisateur choisit le rattachement. Le schéma v4 est un contrat interne d'upstream : toute évolution produit `unsupported_schema` visible, jamais une lecture approximative.
