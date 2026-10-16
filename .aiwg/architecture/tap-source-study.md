# Étude du source claude-tap — interfaces réelles

Date : 16 octobre 2026. Auteur : architecte (Opus). Source : `.runtime/upstream/claude-tap`, commit `e17ed32a16389e8fb3f4f510adc359c48e09211c` (MIT). Lecture du code et des tests uniquement. Aucune base réelle ni aucun identifiant n'a été ouvert. Les références `fichier:ligne` renvoient à ce commit.

## 1. Emplacement de la base
`trace_store.resolve_db_path()` (`trace_store.py:60-70`) :
1. `CLOUDTAP_DB`, s'il n'est pas vide → `Path(v).expanduser().resolve()` ;
2. sinon `$XDG_DATA_HOME/claude-tap/traces.sqlite3` ;
3. sinon `~/.local/share/claude-tap/traces.sqlite3`, **y compris sous Windows** : il n'y a aucune branche `%APPDATA%`.

Le fichier de verrou `traces.sqlite3.write.lock` est voisin de la base (`:36`, `:97`). La base passe en `journal_mode=WAL` à chaque connexion d'écriture (`:1006`). Il faut donc s'attendre aux fichiers `-wal` et `-shm`.

## 2. Schéma (`PRAGMA user_version = 4`)
`_create_v3_tables` + `_create_v4_tables` (`:1180-1247`) :

| Table | Colonnes utiles | Clé |
| --- | --- | --- |
| `sessions` | `id TEXT` (uuid4 de tap), `started_at`, `updated_at`, `date_key`, `client` (ex. `claude`, `codex`, `codexapp`), `proxy_mode`, `status` (`active/complete/empty/error`), `record_count`, `summary_json`, `legacy_source_key`, `legacy_rel_path` | `id` |
| `records` | `session_id`, `record_index` (1, 2, … attribué par `MAX+1`), `turn`, `timestamp`, `payload_json TEXT` | `(session_id, record_index)` |
| `record_blobs` | `session_id`, `hash` (`sha256:<hex>`), `kind` (`json`), `payload_json`, `size_bytes`, `created_at` | `(session_id, hash)` |
| `proxy_logs`, `migration_state` | sans intérêt pour la mémoire | — |

Les enregistrements sont seulement ajoutés : `append_record` (`:128`). Il existe toutefois deux exceptions qui réécrivent ou suppriment : `replace_record_payloads` (`:163`, remplissage a posteriori pour Cursor) et `delete_session*`/`cleanup_old_sessions` (`:408`, `:724`, `:754`). Le curseur `(tap_session_id, record_index)` est donc stable tant que la session existe. Une session peut disparaître, et un même index peut voir son contenu réécrit.

## 3. Pourquoi ne pas instancier `TraceStore`
Même en lecture, `_read_connect` appelle `_ensure_schema_for_read` (`:1062-1081`). Cet appel prend le verrou d'écriture inter-processus, ouvre la base en WAL et exécute `_ensure_schema`. Celui-ci peut créer le schéma, effectuer une migration v2→v3 (renommage et recréation des tables) ou v3→v4, puis faire un commit. Il lève une erreur pour toute autre version (`:1098-1111`). `__init__` crée aussi le dossier parent (`:96`). **Conclusion : Filigree n'importe jamais `claude_tap` et ouvre la base lui-même avec `sqlite3.connect("file:<chemin>?mode=ro", uri=True)`.** Upstream utilise lui-même ce motif pour lire Cursor (`cursor_metadata.py:65`).

## 4. Encodage d'un enregistrement et internement des blobs
Source : `compact_trace.py`, `trace_store._encode_record` (`:1361`) et `_load_record_blob` (`:1415`).
- `payload_json` est soit l'enregistrement brut, soit une enveloppe :
  `{"__claude_tap_compact_record__": {"version": 1, "encoding": "json-blob-ref", "refs": [{"path": "/request/body/messages/3", "hash": "sha256:…", "bytes": N}]}, "record": {…}}`.
- À chaque chemin de `refs`, la valeur est remplacée par `{"__claude_tap_blob_ref__": {"version": 1, "kind": "json", "hash": "sha256:…", "bytes": N}}`. Ce dictionnaire doit contenir **exactement** cette clé (`is_blob_ref`, `:300`).
- Chemins possibles, et seulement ceux-là (`:17-26`) : `/request/body/instructions`, `/request/body/tools`, `/response/body/instructions`, `/response/body/tools`, ainsi que chaque élément `/request/body/input/<i>` et `/request/body/messages/<i>`. Seules les valeurs de 512 octets ou plus sont internées (`MIN_BLOB_BYTES`).
- Le blob vaut `json.dumps(value, ensure_ascii=False, separators=(",", ":"))`. `hash` est `"sha256:" + sha256(blob_utf8)` et `size_bytes` est la longueur en octets (`json_blob_payload`, `:118`). **Le hachage est donc vérifiable** sur `record_blobs.payload_json` tel qu'il est stocké.
- Les blobs sont propres à une session : la recherche se fait sur `(session_id, hash, kind)`.
- Si `refs` est absent ou vide, upstream retombe sur un balayage des chemins connus (`_legacy_compact_ref_paths`, `:221`).
- Pointeurs de type JSON (`~1`, `~0`) : seulement décodés, jamais produits pour ces chemins.
- Une `version` différente de 1 provoque `RuntimeError` dans upstream. Filigree doit **refuser** l'enregistrement, pas le deviner.

## 5. Contenu d'un enregistrement
`proxy._build_record` (`proxy.py:844-880`) et `ws_proxy` (`:407-433`) produisent la structure suivante :
`timestamp, request_id, turn, duration_ms, [transport:"websocket"], request{method, path, headers, body, [ws_events]}, response{status, headers, body, [sse_events|ws_events], [error]}, [upstream_base_url]`.
`TraceWriter._write_locked` ajoute `capture = {client, proxy_mode}` (`trace.py:67-69`, `cli.py:332`). C'est **la seule** métadonnée de capture.
- Les en-têtes sont conservés avec leur casse d'origine. Seuls `authorization`, `cookie`, `x-api-key` et quelques autres sont masqués (`proxy.py:48-82`). Les identifiants de session ne sont pas masqués.
- Avec SSE, `response.body` est reconstruit en message complet (`proxy.py:750-757`). Avec WebSocket, il est reconstruit par `_reconstruct_ws_response_body`.
- `request.body.messages` (Anthropic) et `request.body.input` (Responses) contiennent **tout l'historique** à chaque tour.

## 6. Ce que tap ne fournit pas
- **Aucun `cwd`** : rien dans `sessions` ni dans `capture`. `legacy_source_key` est un hachage du dossier `.traces` hérité, présent seulement pour les sessions migrées. Ce n'est pas un dossier de travail.
- Aucun lien explicite vers une session native : `sessions.id` est un uuid4 propre à tap (`:111`). Une session tap peut couvrir plusieurs conversations natives, par exemple avec `/clear` ou des sous-agents.

## 7. Identifiants natifs réellement présents (vérifiés dans le source ou les tests)
| Client | Emplacement dans le record | Preuve upstream |
| --- | --- | --- |
| Claude Code | en-tête `X-Claude-Code-Session-Id` (casse variable) | `viewer_assets/diff.js:977`, `tests/test_viewer_contracts.py:1337` |
| Claude Code | `request.body.metadata.user_id` = chaîne JSON `{"device_id","account_uuid","session_id"}` | `tests/test_deepseek_compat.py:7` |
| Codex CLI | `request.body.client_metadata["x-codex-turn-metadata"]` (chaîne JSON ou objet) → `session_id`, `thread_id` | `diff.js:55-67`, `tests/test_diff_matching.py:415-469` |
| Codex CLI | en-tête `session_id` / `session-id` | `diff.js:978` |
| Codex App | en-tête `x-codex-app-session-id` ou `request.body.metadata.codex_app_session_id` | `viewer.py:2000` |
| Responses | `request.body.prompt_cache_key` | `diff.js:975` : clé de cache, **pas** un identifiant de session garanti |

Upstream ne garantit pas que ces identifiants sont égaux au `sessionId` des JSONL Claude ni au `session_meta.payload.id` de Codex. L'égalité est une hypothèse à **constater** par correspondance exacte, jamais à présumer. `find_codex_app_session_row` (`trace_store.py:283`) recherche une sous-chaîne dans le premier payload : Filigree ne doit pas reprendre ce comportement.

## 8. Conséquences pour Filigree
1. Lire en `mode=ro` avec `PRAGMA query_only=ON`. Accepter seulement `user_version == 4` et les tables et colonnes listées. Sinon, renvoyer `capability: unsupported_schema` sans rien lire de plus.
2. Utiliser `(tap_session_id, record_index)` comme curseur, et l'empreinte de `payload_json` pour détecter une réécriture.
3. Écrire un décodeur borné propre à Filigree (≈80 lignes) qui reproduit le §4, avec en plus la vérification du hachage et de la taille. Ne pas copier le code upstream.
4. Le dossier ne vient **jamais** de tap. Il vient soit d'une transcription native dont l'identifiant de session est égal à l'identifiant extrait, soit d'un rattachement explicite choisi par l'utilisateur.
5. Le contenu reste une donnée : `user_id`, les en-têtes et `capture.client` décrivent le client, pas l'auteur, et n'authentifient personne.
