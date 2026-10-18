# ADR-0003 — Observateur permanent : démon, collecteurs, journal d'activité par projet

Date : 17 octobre 2026. Auteur : orchestrateur (Opus). Statut : **retenu pour l'implémentation V2**. L'utilisateur a délégué ces arbitrages le 17/10/2026 (« tu es libre et en autonomie ») : les décisions D1 à D14 du [cadrage](v2-vision-cadrage.md) sont donc prises selon leurs recommandations. Complète [ADR-0001](ADR-0001-local-portable-memory.md) et [ADR-0002](ADR-0002-automatic-project-capture.md), qu'il révise sur les points marqués **Révision**.

## Décisions

| ID | Décision |
| --- | --- |
| D1 | Hooks et enregistrement MCP **opt-in** uniquement : commande explicite, diff affiché, sauvegarde horodatée, portée utilisateur, retour arrière. **Révision ADR-0002 option A.** L'amendement de la phrase d'`AGENTS.md` reste à faire par l'humain. Le code n'écrit jamais `AGENTS.md`/`CLAUDE.md`. |
| D2 | Journal d'activité SQLite **par projet** : `projects/<id>/.filigree/activity.sqlite`. C'est une donnée conservée, pas un index jetable. **Révision ADR-0001** pour ce fichier seulement. Il est hors checkpoint git (liste blanche de `git_sync._memory_file`) et hors export. |
| D3 | Aucun appel à un modèle en V2. |
| D4 | La reprise injectée ne contient que les connaissances `accepted`. |
| D5 | Distribution par paquet Python (wheel / PyPI), avec les scripts `install.ps1`/`install.sh` qui épinglent une version. |
| D6 | Chat (ChatGPT, claude.ai) : import d'exports avec projet explicite uniquement. |
| D7 | Processus : extra facultatif, décoratif, jamais une preuve. |
| D8 | claude-tap devient une source d'enrichissement, plus un prérequis (le collecteur v0.1 est conservé tel quel). |
| D9 | `filigree probe` : sonde en lecture seule, qui produit seulement des comptages et des noms de champs. |
| D10 | Rétention du journal : 90 jours par défaut (`activity.retention_days`). |
| D11 | Pas de rattrapage historique automatique. La ligne de base v0.1 est conservée. |
| D12 | Windows est la plateforme de référence. macOS et Linux sont générés et testés de façon synthétique. |
| D13 | `auto_create` ne s'applique qu'à l'intérieur des racines autorisées. |
| D14 | Une sonde en échec rend la source `unsupported` et visible. Aucune lecture approximative. |

## Amendement du 2026-10-18 : D11 et `filigree backfill`

D11 vise l'absence de rattrapage *automatique*. Une commande explicite de l'utilisateur, `filigree backfill`, peut remettre les curseurs au début (claude-tap, transcriptions natives, journal d'activité) pendant que l'agent et la capture sont arrêtés. Elle n'importe rien elle-même : les cycles suivants rejouent l'historique par les mêmes chemins que le direct, donc sans changement des règles de preuve (rattachement seulement par identifiant natif résolu vers un dossier, sinon en attente), de dédoublonnage et d'exclusion. Pendant le rejeu, claude-tap est relu entièrement avant toute transcription native. Les registres de dédoublonnage tap/natif ne sont plus plafonnés, puis ils reviennent à leur taille normale. Un élément que la mémoire contient déjà par l'autre canal n'est pas importé une deuxième fois. Une base claude-tap verrouillée ou corrompue fait refuser la commande. Limites connues :
- une pause passée n'a pas laissé de trace durable, donc son contenu est relu, sauf les intervalles que la capture connaît encore ;
- un texte tronqué ou normalisé autrement d'un canal à l'autre peut échapper au dédoublonnage.

## Contrats

### Réglages (`<data-dir>/.capture/capture.json`)
On ajoute `allowed_roots` : `null` ou une liste de chemins absolus.
- `null` conserve le comportement v0.1, pour la compatibilité avec les installations existantes.
- `filigree setup` écrit une liste.
- Avec une liste, une session dont le dossier n'est sous aucune racine reste en attente (`outside_roots`), clé seule, sans texte, sans projet créé.

On ajoute aussi `activity` : `{"enabled": bool (true), "retention_days": int 1..3650 (90), "turn_proposals": bool (true)}`. `turn_proposals=false` arrête les propositions par tour de la v0.1 ; seuls le journal et les fiches de session subsistent. Une valeur malformée désactive la capture, comme en v0.1.

### Clé locale et API
- `<data-dir>/.runtime/agent.key` : 43 caractères ou plus en URL-safe, créé une seule fois, permissions restreintes au mieux selon l'OS.
- `LocalServer` utilise cette clé comme jeton. **Toute** route `/api/*` exige `X-Filigree-Token`, sauf `GET /api/bootstrap` qui la remet à la page de même origine (contrôles `Host`/`Origin`/`Sec-Fetch-Site` de la v0.1).
- Un processus du même compte pourrait lire la clé dans le fichier : cette limite est documentée.

### Processus
- `filigree agent [--port N]` est le démon. Il sert l'API et l'interface, fait tourner la capture v0.1 et le pipeline d'activité, et écrit `.runtime/agent.json` `{pid, port, started_at, version}`. Il le retire à l'arrêt.
- `filigree serve` : si un démon répond pour ce dossier de données, il affiche son URL et s'arrête. Sinon il garde son comportement v0.1.
- MCP stdio : il ne capture jamais.

### Démarrage automatique (`filigree/service.py`)
`plan(system, python, data_dir, home, env) -> dict` est pur et testable. `apply(plan, runner)` et `remove(plan, runner)` passent par un exécuteur injectable.
- **Windows** : valeur `Filigree Agent` sous `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (`winreg`, sans admin), commande `"<pythonw>" -m filigree --data-dir "<d>" agent`.
- **macOS** : `~/Library/LaunchAgents/dev.filigree.agent.plist` avec `KeepAlive`.
- **Linux** : `~/.config/systemd/user/filigree-agent.service` avec `Restart=on-failure`.

Les tests n'écrivent jamais dans le vrai registre ni dans le vrai `HOME`.

### Collecteurs (`filigree/collectors/`)
Chaque collecteur expose `name`, `probe() -> {"status": "ok"|"missing"|"unsupported", "detail": str, "fields": {…comptages}}` et `discover() -> list[SessionInfo]`. Ils lisent tout en lecture seule (SQLite en `?mode=ro`), avec une lecture bornée.

`SessionInfo` contient : `client`, `collector`, `native_id`, `key` (`<client>:<racine-source-hash8>:<native_id>`), `cwd`, `entrypoint`, `model`, `version`, `parent_native_id`, `started_at`, `last_activity`, `archived`, `transcript` (chemin ou None).

Collecteurs : `claude_code` (transcriptions, sous-agents), `claude_desktop` (`claude-code-sessions/**/local_*.json`, chemins Roaming et MSIX, **métadonnées seulement**), `codex_state` (`state_5.sqlite` `threads` + `thread_spawn_edges`), `codex_rollout` (`session_meta` ; `.zst` signalé non lu sans `zstandard`), `claude_tap` (capacité v0.1).

### Résolution (`filigree/resolver.py`)
Elle est extraite de `Capture._resolve_native_uncached`, sans changement de comportement v0.1, puis complétée :
1. Contrôle des racines autorisées.
2. **Worktree prouvé** : `<d>/.git` est un fichier `gitdir: <repo>/.git/worktrees/<n>`, `<repo>/.git/worktrees/<n>/gitdir` renvoie à `<d>/.git`, et `<repo>` est un projet enregistré. Le résultat est ce projet. Lecture de fichiers seulement, sans sous-processus.
3. Sinon, règles v0.1.

Le mode `create=False` sert aux vues : il ne crée jamais de projet.

### Journal d'activité (`filigree/activity.py`, `filigree/extract.py`)
Schéma `user_version=1` :
- `events(event_id TEXT PK, session_key, client, kind, ts_source, ts_observed, cwd, summary, files TEXT json, provenance TEXT json, outside_project INT)` ;
- `sessions(session_key PK, client, entrypoint, model, parent_key, first_ts, last_ts, cwd, event_count, ended INT)`.

`kind` ∈ {`user_prompt`, `assistant_text`, `tool_call`, `tool_result`, `file_change`, `command`, `test_result`, `error`, `commit`, `session_start`, `session_end`}. Le `summary` fait au plus 280 caractères et passe par l'expurgation v0.1 **avant** la coupe. L'extraction est déterministe, et le raisonnement, les prompts système et les blocs injectés sont exclus comme en v0.1. On écrit d'abord le journal, et l'état du curseur n'avance qu'ensuite. L'identifiant `event_id` est stable (identifiant d'élément source), ce qui déduplique reprises et forks.

### Distillation (`filigree/distill.py`)
**Fiche de session** : une proposition par session et une seule (URI `filigree:session-sheet:<session_key>`).
- Elle est mise à jour par révision tant qu'elle est `proposed`.
- Si elle est `accepted` ou `rejected`, une proposition « suite » est créée.
- On la déclenche après 10 minutes d'inactivité ou à `session_end`.

**Chevauchements** : au moins deux sessions modifient le même fichier dans les 15 dernières minutes, hors liste d'ignorés.

### MCP et hooks (V2.2)
- `filigree mcp` limite sa portée au projet du dossier courant, ou de `--project-folder`. `--all-projects` est explicite.
- Nouveaux outils en lecture : `project_activity` et `active_sessions`, avec un avertissement « données non revues ». `handoff` reçoit l'option `accepted_only`.
- `filigree hooks install|uninstall|status --client claude|codex [--inject] [--dry-run]` :
  - hook de commande `python -m filigree signal …` en portée utilisateur ;
  - sauvegarde `*.filigree-backup-<horodatage>` et journal `.runtime/install-log.jsonl` ;
  - `signal` ne transmet que `{client, session_id, event}`, en moins de 1 s, et sort toujours avec le code 0 ;
  - `--inject` (Claude `SessionStart`) écrit sur la sortie standard les connaissances acceptées du projet.

### Imports de chat (V2.3)
`filigree import-export FILE --project ID` lit un export ChatGPT (`conversations.json`, arbre `mapping`) ou claude.ai (`chat_messages`), fourni en `.json` ou `.zip`, et produit des propositions. Le projet est toujours explicite.

## Conséquences

- Les tests v0.1 restent un filet de non-régression. Ceux qui lisent l'API sans jeton sont mis à jour, puisque la lecture est désormais authentifiée.
- Les nouvelles sources reposent sur des formats non contractuels, qui doivent être sondés avant usage.
- Le journal ne peut pas être reconstruit après une purge des agents, ce qui est documenté.
