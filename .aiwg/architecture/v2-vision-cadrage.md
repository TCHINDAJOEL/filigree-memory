# Filigree V2 — cadrage : observateur local permanent des agents IA

Date : 17 octobre 2026. Auteur et synthétiseur : orchestrateur (Opus). **Révision 2** : intègre trois revues indépendantes ([architecture](../testing/v2-review-architecture.md), [sécurité](../testing/v2-review-securite.md), [produit](../testing/v2-review-produit.md)). Le traitement de chaque constat est consigné dans [la synthèse](../testing/v2-review-synthesis.md). Statut : **cadrage soumis à validation utilisateur, aucune implémentation**. Complète [la vision v0.1](../requirements/vision.md), [ADR-0001](ADR-0001-local-portable-memory.md) et [ADR-0002](ADR-0002-automatic-project-capture.md). Leurs révisions passeront par une ADR-0003 acceptée par l'utilisateur, avant tout code.

## En bref (pour un lecteur pressé)

- **Quoi** : Filigree devient un petit service qui démarre avec Windows. Il repère seul les sessions Claude Code et Codex, les range dans le bon projet et en tire une histoire lisible : ce qui a été fait, modifié, essayé, et ce qui a échoué.
- **Ce qui marche automatiquement** : Claude Code (terminal et onglet Code de l'application Claude), Codex (terminal, extension IDE, application Codex). Ces outils écrivent eux-mêmes sur le disque un journal qui indique dans quel dossier ils travaillent.
- **Ce qui ne marche pas automatiquement** : les conversations ChatGPT et Claude « chat ». Elles sont stockées chez l'éditeur, sans dossier de projet. Elles ne pourront entrer que par un export que vous déclenchez.
- **Sécurité** : rien n'est lu avant votre accord. Seuls les dossiers que vous autorisez sont suivis, rien ne sort de l'ordinateur, et rien n'est modifié dans la configuration de vos agents sans votre accord explicite et réversible.
- **Décisions** : Filigree reconstitue fidèlement les *activités* (fichiers, commandes, tests, commits). Reconnaître une *décision* dans une conversation demande un modèle de langage. C'est une option ultérieure, désactivée par défaut, et le résultat reste une proposition à valider.
- **Ordre** : Windows d'abord. V2.0 apporte l'installation, le service et la vue « sessions du jour ». V2.1 apporte la compréhension multi-sessions, V2.2 la transmission aux agents, V2.3 les exports de chat.

### Ce que V2 ne fera pas

| Outil | Automatique ? | Pourquoi |
| --- | --- | --- |
| Claude Code (terminal, onglet Code de Claude Desktop) | **Oui**, sous réserve des sondes du §5 | L'outil écrit son journal et son dossier sur le disque |
| Codex CLI, extension IDE, application Codex | **Oui**, sous réserve des sondes du §5 | Idem ; les tâches **Codex cloud** sont exclues (non locales) |
| Claude Desktop « chat » et Cowork, claude.ai | **Non** : export manuel, ou note poussée volontairement par MCP | Conversation stockée sur les serveurs, pas de dossier |
| ChatGPT (bureau, web) | **Non** : export manuel uniquement | Conversation sur les serveurs. MCP limité aux serveurs distants. Les CGU interdisent l'extraction automatisée |

Filigree ne lit pas le raisonnement caché des modèles, ni les prompts système ou les secrets. Il n'intercepte pas le trafic, ne lit pas les caches internes des applications de chat et ne synchronise rien dans le cloud.

### Glossaire minimal

**Session** : une conversation suivie avec un agent, du lancement à la fermeture. **`cwd`** : dossier de travail dans lequel l'agent a été lancé. **Collecteur** : module de Filigree qui sait lire le journal d'un outil donné. **Hook** : point d'extension où un agent appelle un programme externe à certains moments (début de session, fin de tour…). **MCP** : protocole par lequel un agent interroge un outil, ici la mémoire Filigree. **Worktree** : second dossier de travail rattaché au même dépôt git. **Loopback** : adresse réseau interne à la machine (127.0.0.1), inaccessible depuis l'extérieur.

Légende des preuves : **[D]** documenté par l'éditeur · **[O]** observé sur le poste de développement le 17/10/2026 (noms de champs seulement, aucun contenu lu) · **[C]** rapporté par la communauté · **[?]** à vérifier. **[C] et [?] ne fondent jamais une promesse faite à l'utilisateur** : il faut d'abord une sonde (§5).

---

## 1. Vision

> **On installe Filigree une fois et on choisit les dossiers à suivre. On travaille ensuite comme d'habitude, dans autant de projets et de terminaux qu'on veut. Filigree sait quels agents travaillent, sur quel projet et sur quoi. Il conserve une histoire sourcée de ce qui a été fait, essayé et changé, relisible par un humain et transmissible à l'agent suivant.**

| Axe | v0.1 (livrée) | V2 |
| --- | --- | --- |
| Mise en route | `pip install`, `filigree serve`, script de démarrage facultatif | Une commande, un accord, service au démarrage de session Windows (macOS et Linux ensuite) |
| Couverture | claude-tap + transcriptions Claude Code / Codex | Registre de collecteurs : base d'état Codex, sessions Code de Claude Desktop, signaux de hooks facultatifs, exports |
| Compréhension | Une proposition par tour de conversation | Journal d'activité par projet, puis fiches de session, chronologie multi-agents et chevauchements |

### Principes

1. **Un accord, ensuite zéro geste.** L'installation pose une question : « suivre ces dossiers ? ». La liste est pré-remplie à partir des dossiers où vos agents ont travaillé récemment. Ensuite il n'y a plus rien à lancer.
2. **Consentement préalable (opt-in).** Seuls les dossiers racines autorisés sont capturés. Hors de ces dossiers, une session ne produit qu'une clé en attente, sans texte. Rien n'est lu avant l'accord.
3. **Exactitude avant exhaustivité.** On garde l'invariant d'`AGENTS.md` : on ne rattache jamais une trace par nom, par récence ou par timing. La V2 ajoute des preuves, pas des heuristiques. Les preuves restent des **revendications locales**, pas une authentification (§6).
4. **Passif par défaut, actif seulement par consentement explicite, affiché et réversible.** Cela couvre les hooks, l'enregistrement MCP et la reprise injectée. L'invariant d'`AGENTS.md` « pas de modification silencieuse » est maintenu. Sa formulation doit cependant être amendée par l'humain pour autoriser ces écritures consenties (D1).
5. **Des propositions, jamais des décisions.** Toute production automatique est une proposition, et un humain l'accepte.
6. **Strictement local.** Pas de réseau, pas de télémétrie, aucun appel à un modèle distant en V2.
7. **Évolution de la v0.1** : store Markdown, adaptateurs en lecture seule, règles de rattachement et filtres d'expurgation sont conservés.

---

## 2. Fonctionnalités nécessaires

| # | Fonction | Exigence servie | Point de départ v0.1 |
| --- | --- | --- | --- |
| F1 | **Installation en une ligne**, version épinglée et intégrité vérifiable, + `filigree setup` avec un seul accord par défaut | §1 de la demande | `pyproject` sans dépendance, script `.ps1` |
| F2 | **Service permanent** : démon au démarrage de session, relance sur échec, un seul démon par dossier de données | §3 | `capture run`, `ProcessLock`, raccourci Startup |
| F3 | **Registre de collecteurs**, contrat commun (§8) | §2, évolutivité | Adaptateurs déjà séparés (`tap_source`, `native_index`) ; c'est la classe `Capture` qui couple tout |
| F4 | **Détection de sessions** par l'écriture des stores des agents ; signaux de hooks facultatifs | §2 | Balayage toutes les 3 s |
| F5 | **Résolution de projet** : dossiers racines autorisés, ancêtre enregistré, worktree prouvé, racine git | §4 | `project_for_path`, `_git_root` |
| F6 | **Identité de session et d'agent** : client, point d'entrée, version, modèle, sous-agent et mère, racine source | §5 | `agent` = libellé déclaratif |
| F7 | **Journal d'activité normalisé par projet** | §6 | Une entrée Markdown par tour |
| F8 | **Extraction déterministe d'activités** : fichiers, commandes, tests, erreurs, commits, branches | §6 | Absente |
| F9 | **Vue « sessions du jour »** (V2.0), puis chronologie projet multi-sessions (V2.1) | §5, §7 | Vue Capture |
| F10 | **Couverture et santé** : par outil, source, niveau de preuve et état de sonde ; indicateur « capture active » ; « ce que Filigree a lu aujourd'hui » | Fiabilité, transparence | `capture status` |
| F11 | **Consentement et périmètre** : racines autorisées, pause, rétention, purge, désinstallation | Vie privée | pause, exclusion |
| F12 | **Accès agents** : outils MCP en lecture **limités au projet du client** | Transmission | MCP lecture + proposition |

## 3. Fonctionnalités complémentaires

★ = recommandée pour la V2. Le lot cible est indiqué.

- ★ **Fiche de fin de session** (V2.1). Une proposition déterministe rassemble la demande de l'utilisateur au premier tour, les fichiers touchés, les commandes et leurs codes de sortie, les tests et les erreurs non résolues. Clé d'idempotence = session + version de l'extracteur : une session reprise met à jour sa fiche au lieu d'en créer une seconde.
- ★ **Arbre des sous-agents** (V2.1). Il s'appuie uniquement sur les liens déclarés : Codex `thread_spawn_edges` [O] et Claude `subagents/agent-*.jsonl` [C].
- ★ **Chevauchements** (V2.1). Deux sessions actives modifient le même fichier source dans les 15 dernières minutes, hors liste d'exclusions (lockfiles, fichiers générés, `.aiwg/`, etc.). Alerte non bloquante, testée contre les faux positifs.
- ★ **Reprise au démarrage d'une session** (V2.2, opt-in par projet). Elle injecte **uniquement les connaissances acceptées**. L'activité non revue reste accessible par un outil MCP explicite qui la signale comme non fiable : elle n'est jamais injectée (voir D4).
- **Rattachement des commits** : un SHA présent dans une session (sortie d'outil, `git_sha` Codex [O]) est lié à cette session, ce qui relie le code à son pourquoi.
- **Digest par projet** (Markdown) : activité, tentatives abandonnées, questions ouvertes.
- **Consommation** : jetons par session quand la source les expose (`tokens_used` Codex [O]).
- **Boîte de dépôt d'exports** (V2.3) : on dépose un export ChatGPT ou claude.ai, puis on choisit **explicitement** son projet.
- **Décisions candidates et contradictions** (V2.x, option D3) : nécessitent un modèle **local**, sont désactivées par défaut et restent des propositions.

**Ce que la V2 ne promet pas** : les fonctions V2.0 à V2.2 reconstituent des **activités et des changements**. Les **décisions** restent saisies ou validées par un humain, comme en v0.1, tant que D3 n'est pas tranchée.

---

## 4. Détection des agents

| Famille | Mécanisme | Rôle dans Filigree | Coût / risque |
| --- | --- | --- | --- |
| **A. Stores des agents** (passif) | Lecture seule des fichiers et bases que les agents écrivent | **Seule source de preuve et de contenu** | Formats non contractuels : sonde par source |
| **B. Hooks / notify** (opt-in) | Un hook prévient Filigree qu'une session a commencé, avancé ou fini | **Signal de réveil uniquement**. Le contenu du hook n'est jamais une preuve, et Filigree ne lit jamais un chemin qu'il fournit. Il relit la session dans le store de l'agent, sous les racines configurées | Modifie la config de l'agent : opt-in, diff, sauvegarde, retour arrière |
| **C. Proxy claude-tap** | Base de traces existante, lue en lecture seule | Enrichissement (usage, requêtes complètes), plus de prérequis (D8) | En-têtes jamais lus |
| **D. Processus** (V2.1, extra facultatif) | Liste des exécutables d'agents connus | **Décoratif** : « un agent tourne », PID affiché. Jamais un champ de preuve, jamais persistant d'une session à l'autre | `cwd` Windows via PEB fragile ; lignes de commande jamais stockées |

**Recommandation.** Le moteur est la famille A. On surveille les fichiers par `stat` adaptatif, plafonné : nombre de fichiers par cycle, profondeur, fenêtre de fichiers récents. Le rythme est de 1-2 s quand une session est active et de 15-30 s au repos. La famille B ne fait que réduire la latence. Sans aucun hook, Claude Code et Codex sont déjà couverts.

## 5. Possibilités et limites par outil

| Outil | Source passive | Dossier de projet | Accélérateur opt-in | Limites | Couverture V2 |
| --- | --- | --- | --- | --- | --- |
| **Claude Code CLI** | `~/.claude/projects/<dossier>/<session>.jsonl` [D] ; sous-agents `<session>/subagents/` [C] | `cwd` sur chaque ligne [D/O] | Hooks dont `SessionStart`/`Stop`/`SessionEnd`, avec `session_id` et `cwd` [D] | Format « interne, change selon les versions » [D] ; purge à 30 j [D] ; `CLAUDE_CODE_SKIP_PROMPT_HISTORY` [D] | Complète, **sous réserve de sonde** |
| **Claude Desktop, onglet Code** | Mêmes transcriptions [D, mode 3P] ; `claude-code-sessions/**/local_*.json` : **métadonnées seulement** (`cliSessionId`, `cwd`) [C/O] ; chemin MSIX distinct [C] | Oui | Hooks partagés [?] | Métadonnées Desktop non documentées | Complète, **sous réserve de sonde** |
| **Claude Desktop chat / Cowork** | Aucune : IndexedDB = état de l'interface [C], **non lu** | Non | MCP local, en poussée volontaire [C] | Pas de flux | Export + MCP |
| **Codex CLI** | `~/.codex/sessions/**/rollout-*.jsonl` (`session_meta`) [C] ; `state_5.sqlite` `threads` [C/O] | `session_meta.cwd`, `threads.cwd` | `hooks.json` [D/C] ; `notify` [D] | `.jsonl.zst` après ~7 j, `archived_sessions/` [C] ; `source`/`originator` non fiables [C] | Complète, **sous réserve de sonde** |
| **Codex App, extension IDE** | Mêmes stores, partagés via l'app-server [D] | Oui | Idem CLI | Synchronisation imparfaite [C] ; **cloud exclu** | Complète en local, **sous réserve de sonde** |
| **ChatGPT** | Aucune, cache non lu | Non | Aucun (MCP distant seulement [D]) | CGU : pas d'extraction automatisée [D] | Export uniquement |
| **claude-tap** | `traces.sqlite3` schéma 4 [O] ; le README actuel décrit des JSONL [D] | Via lien natif | — | Divergence à re-sonder | Enrichissement |

**Frontière de lecture (cohérente avec les CGU).** Filigree lit (1) les journaux que les **agents de code** écrivent pour l'utilisateur et (2) dans les fichiers propres à une application, **uniquement les métadonnées d'identité** (identifiant de session, dossier) qui renvoient vers ces journaux. Il ne lit jamais le contenu d'une conversation dans le cache interne d'une application. Pour les exports, Filigree importe un fichier que l'utilisateur a lui-même obtenu et déposé. La conformité aux conditions des éditeurs reste à faire confirmer (voir la synthèse, S-13).

**Sondes obligatoires avant toute promesse (D9).** Pour chaque ligne « sous réserve », un test documenté sur une installation réelle doit vérifier :
- l'emplacement ;
- les champs requis ;
- la version de l'outil ;
- un rattachement de bout en bout.

Le résultat est consigné dans `.aiwg/testing/`. Une sonde en échec rend la source « non prise en charge » dans la page Couverture.

**Respect des choix des outils.** Une purge, `CLAUDE_CODE_SKIP_PROMPT_HISTORY` ou une session archivée expriment une intention de l'utilisateur. Filigree ne les contourne pas : il ne fait aucun rattrapage automatique de l'historique. Le rattrapage est proposé **par projet**, à la demande explicite de l'utilisateur, et les sessions archivées sont exclues par défaut (D11).

---

## 6. Corréler terminaux, sessions et agents

### Modèle d'identité

```text
Projet ─┬─ Racine(s) : dossier enregistré (+ worktrees prouvés)
        └─ Session  clé = <client>:<racine-source>:<id natif>   (la racine distingue deux CLAUDE_CONFIG_DIR / CODEX_HOME)
              ├─ Agent   : client, point d'entrée, version, modèle          (déclaratif)
              ├─ Lignée  : session mère (lien déclaré uniquement), rôle      (déclaratif)
              ├─ Canaux  : transcription, base d'état, tap, signal de hook  (preuves associées)
              └─ Activité: événements normalisés (§7), chacun avec son cwd d'origine
```

### Règles

1. **Session → dossier.** Le `cwd` doit être écrit dans le store de l'agent, sous une racine configurée, pour cet identifiant exact. Un hook ne fournit jamais le `cwd`. Si une session a plusieurs `cwd` qui mènent à des projets différents, on garde le comportement de la v0.1 : `ambiguous_cwd`, mise en attente. Une **session est rattachée au projet de son premier `cwd`**. Un événement survenu hors de ce projet (changement de dossier en cours de route) est marqué `outside_project` et n'est jamais déplacé vers l'autre projet.
2. **Dossier → projet.** Il faut d'abord que le dossier soit sous une **racine autorisée**, sinon la session reste en attente avec sa clé seulement. On cherche ensuite l'ancêtre enregistré le plus proche, puis un **worktree prouvé**, puis la racine git (création si l'option `auto_create` est active dans une racine autorisée), puis le dossier lui-même. Un worktree est prouvé quand le `.git` du dossier pointe vers `<repo>/.git/worktrees/<nom>`, que ce dossier contient un `gitdir` qui **revient** vers le worktree, et que `<repo>` est déjà un projet enregistré. On lit des fichiers, sans lancer de sous-processus git. **Deux clones distincts restent deux projets**, sauf regroupement explicite par l'utilisateur. Un sous-module n'est jamais fusionné avec son parent.
3. **Session → session mère.** Uniquement par des liens déclarés. Un sous-agent est rattaché par **sa propre** preuve de dossier, jamais par héritage de la mère.
4. **Reprise et fork** (`--resume`, `codex resume`, fork). La session copiée garde sa propre clé. Les éléments recopiés sont dédupliqués par l'identifiant d'élément de la source (`uuid` Claude, identifiant d'item Codex). Ainsi, ni le journal ni les fiches ne contiennent de doublons.
5. **Processus.** Ils ne servent jamais au rattachement. Un PID est étiqueté avec son heure de démarrage pour éviter les recyclages.
6. **Multi-terminaux.** Chaque session reste distincte même quand dossier, heure et agent coïncident. Les sessions sont regroupées seulement dans la chronologie du projet.

**Limite assumée.** Les preuves sont des données locales. Un programme qui tourne sous le même compte peut fabriquer une fausse transcription. Ce n'est pas plus grave qu'en v0.1, mais la reprise injectée en ferait un canal d'influence. C'est pourquoi elle se limite aux connaissances acceptées par un humain.

### Vision cohérente des sessions concurrentes

- Chronologie par projet triée par `(ts_source, source, ordre local)`. On stocke aussi `ts_observed` (horloge du démon). Un horodatage source dans le futur, au-delà de 5 minutes, est signalé.
- Les rapprochements se font par artefacts partagés (même fichier, commit, branche, test). Ce sont des relations **proposées**.
- Une information contradictoire produit deux propositions sourcées, reliées par une relation `conflicts_with` elle aussi proposée. Une capture ne modifie jamais une décision acceptée.

---

## 7. Récupération, nettoyage et structuration

```text
Collecteurs (lecture seule) → 1. Extraction bornée + expurgation (v0.1) → 2. Normalisation → 3. Rattachement (§6)
   → 4. Journal d'activité du projet → 5. Extraction d'activités (déterministe) → 6. Propositions Markdown (gouvernance v0.1)
```

**Événement normalisé** : `event_id` (URI stable), `session_key`, `agent{…}`, `ts_source`, `ts_observed`, `cwd`, `kind` ∈ {`user_prompt`, `assistant_text`, `tool_call`, `tool_result`, `file_change`, `command`, `test_result`, `error`, `commit`, `session_start`, `session_end`}, `summary` (≤ 280 caractères, expurgé), `files[]`, `provenance{collector, evidence, source_uri}`.

**Journal d'activité (révision explicite de l'ADR-0001, à acter dans l'ADR-0003) :**
- **Emplacement : un fichier par projet**, `memory/projects/<id>/.filigree/activity.sqlite`. Il suit le projet quand on le déplace, l'exporte ou le supprime. Filigree l'**exclut** des checkpoints git et des exports. Il refuse tout dossier de données placé dans un dossier synchronisé (OneDrive, Dropbox) sans confirmation.
- **Statut : donnée conservée, pas un index jetable.** Les sources des agents sont purgées (Claude à 30 jours, Codex compressé à 7 jours), donc le journal ne peut pas être reconstruit après coup. L'ADR-0003 doit le dire et révoquer pour lui la règle « tout index doit être jetable ». Le Markdown reste la source de vérité des **connaissances gouvernées**.
- **Indépendance.** Une proposition embarque toujours son extrait (règle de l'ADR-0001). Elle ne dépend jamais d'une ligne du journal, qui peut être purgée.
- **Sessions non rattachées** : on stocke la clé et le motif, **sans texte**, comme le veut l'ADR-0002.
- **Pas de pointeur vers la source brute** servi par l'API ou MCP. Seuls le résumé expurgé et l'URI de provenance sont exposés.
- **Rétention par défaut** : 90 jours, configurable (D10). La purge est irréversible et journalisée. Le schéma porte un `user_version`, les migrations ne vont que vers l'avant, une sauvegarde est faite avant migration, et le démon refuse une version plus récente que la sienne.

**Protocole de reprise.** Chaque étape est idempotente par clé :
1. On écrit les événements dans le journal du projet, par `event_id` (transaction SQLite).
2. On fait ensuite avancer le curseur du collecteur.
3. La distillation écrit ses propositions par clé d'idempotence (session + version de l'extracteur), ce qui permet de rejouer une reprise sans doublon.

Le curseur n'avance qu'après validation de l'écriture. C'est le principe de la v0.1 (`import_events` puis état), appliqué à deux stores.

**Volume.** Le Markdown ne reçoit plus que les sorties distillées : fiches, échecs notables, décisions saisies. On évite ainsi l'écriture d'une entrée par tour (65 s pour 3 000 entrées en v0.1). La distillation écrit par lots courts, afin de ne pas monopoliser le verrou du workspace face à l'interface et à MCP.

---

## 8. Architecture cible

```text
┌──────────────────────── filigree agent (démon unique, utilisateur courant, sans console) ────────────────────────┐
│ Détecteur (stat adaptatif)  ─▶ Collecteurs ─▶ Normaliseur ─▶ Résolveur d'identité ─▶ Journal par projet ─▶ Distillateur │
│ Signal hook (POST authentifié, réveil seul) ┘   claude-code · claude-desktop-code · codex-state · codex-rollout · tap   │
│ API HTTP loopback (jeton requis, lecture comprise) + interface web                                           │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
        ▲ CLI (client de l'API)        ▲ MCP stdio, un processus par client agent : lecture du store + proposition,
                                         sous le verrou de workspace v0.1, limité au projet du client
```

**Rôles des processus** :
- `filigree agent` est **le seul** processus qui capture. Il sert aussi l'API et l'interface : fermer le navigateur n'arrête rien.
- `filigree serve` devient un alias qui ouvre l'interface du démon, ou le démarre s'il est absent.
- Les processus MCP ne capturent rien.
- Tous les écrivains du Markdown partagent le verrou de la v0.1.

| Composant | Choix | Écarté |
| --- | --- | --- |
| Démarrage | Windows : tâche planifiée à l'ouverture de session, relance sur échec (repli : raccourci Startup v0.1). Ensuite LaunchAgent (macOS) et `systemd --user` (Linux) | Service système (admin, session 0) |
| Installation | Paquet PyPI `filigree-memory==<version>` via `uv tool` ou `pipx`. Script `install.ps1` publié **avec chaque release** (empreinte SHA-256 dans les notes de version, tag signé), qui épingle la version. Documentation : l'installation en une ligne est la voie courte ; « télécharger, lire, exécuter » est la voie vérifiable. Aucun droit administrateur, aucune exclusion antivirus demandée | Script non versionné ou téléchargement d'un binaire sans vérification |
| Authentification locale | Secret durable par installation, dans un fichier lisible par l'utilisateur seul (`<data-dir>/.runtime/agent.key`). Exigé pour **toute** requête de l'API, lectures comprises. Contrôle d'`Origin` et d'`Host` conservé (v0.1) ; port stable configurable | Jeton par processus (v0.1), inutilisable par un hook |
| Signal de hook | Hook `command` minimal ou `http` avec en-tête lu depuis le fichier de clé. Charge utile limitée à `{client, session_id, event}`. Débit borné. Échec silencieux en moins de 50 ms côté agent | Hook qui transmet du contenu ou un chemin |
| Surveillance | `stat` stdlib, plafonné ; `watchdog` en extra facultatif | Dépendance obligatoire |
| Processus | Extra facultatif `[process]` (`psutil`), V2.1, liste blanche d'exécutables d'agents | Code natif |
| Journal | SQLite stdlib en WAL, un fichier par projet | Base globale |
| Collecteur | `probe() → capability` · `discover() → sessions` · `read(cursor) → events, cursor'` · `evidence(session) → {cwd, ids}`. Erreurs isolées par collecteur (v0.1 `_isolated`) | Logique par agent dans `Capture` |
| MCP | Portée = projet du dossier du client (`project_for_folder`). Lecture d'un autre projet seulement si l'utilisateur l'a autorisé explicitement | Accès global |

**Budget mesuré (critère de sortie)** : au repos, CPU < 1 % en moyenne sur 10 minutes et RAM < 100 Mo. Aucune écriture tant qu'aucune session n'est active. Détection d'une nouvelle session < 5 s (p95) avec hook, < 30 s sans hook.

**`filigree setup`** : un accord par défaut, des options détaillées en mode avancé, tout réversible par `filigree uninstall`.
1. Afficher les agents détectés et la **couverture** attendue (tableau « Ce que V2 ne fera pas »).
2. Proposer les **dossiers racines à suivre**, pré-remplis à partir des `cwd` récents lus dans les **métadonnées** (pas le contenu). L'utilisateur coche, valide : **c'est le seul accord obligatoire**.
3. Activer le démarrage automatique et ouvrir la page Couverture.
4. Avancé, chaque élément avec diff, sauvegarde horodatée, portée **utilisateur** seulement (jamais dans le dossier du projet, ce qui éviterait de les committer) et ligne dans un journal d'installation :
   - hooks ;
   - enregistrement MCP ;
   - rattrapage historique par projet.

`filigree status` liste les artefacts posés (tâche planifiée, fichiers modifiés et leurs sauvegardes), et la page Couverture montre en permanence si la capture est active.

---

## 9. Écart avec la v0.1

| Module | Sort | Changement |
| --- | --- | --- |
| `store.py` | Garder | Écritures par lots ; propositions distillées idempotentes |
| `tap_source.py`, `native_index.py` | Garder | Enveloppés comme collecteurs du registre. Les nouvelles sources (`state_5.sqlite`, `local_*.json`) deviennent des **collecteurs distincts**, pas des extensions de `native_index` |
| `capture.py` : classe `Capture` | Refondre progressivement | Séparer registre, résolveur (§6 + racines autorisées + worktrees prouvés) et écriture. La suite de tests v0.1 sert de filet de non-régression |
| `server.py` + `static/` | Étendre | Démon `filigree agent`, clé durable, lecture authentifiée, vues Sessions du jour, Chronologie, Couverture |
| `mcp.py` | Étendre | Portée projet, outils de lecture d'activité signalés non fiables, toujours sans acceptation |
| `importers.py` | Étendre | Exports ChatGPT et claude.ai |
| `scripts/install-capture-startup.ps1` | Remplacer | `filigree setup` / `uninstall` |
| Nouveaux | — | `collectors/`, `activity.py`, `distill.py`, `service/` |

Note : la v0.1 crée aujourd'hui **un projet par worktree** (racine git du worktree). La règle des worktrees prouvés change ce comportement, et une migration de regroupement doit être proposée à l'utilisateur, sans être automatique.

**Invariants de `AGENTS.md`** :

| Invariant | Statut V2 |
| --- | --- |
| La mémoire d'un vrai projet appartient à son dossier local ; jamais de rattachement par nom, récence ou timing | Maintenu, et renforcé : journal par projet, racines autorisées |
| Le texte source est une donnée non fiable | Maintenu ; la reprise injectée se limite à l'accepté |
| Imports et capture créent des propositions ; aucune auto-approbation | Maintenu |
| Préserver historique et provenance | Maintenu ; les propositions embarquent leurs extraits |
| Ne pas committer `.runtime`, traces, conversations, mémoires privées | Maintenu ; journal exclu des checkpoints |
| Dépendances d'exécution minimales | Maintenu ; extras facultatifs |
| Lecture seule des sources | Maintenu pour les stores des agents |
| Pas de modification silencieuse de la configuration d'un agent | **Formulation à amender par l'humain** : les écritures restent interdites sans consentement, mais deviennent possibles avec consentement, diff, sauvegarde et retour arrière (D1) |

---

## 10. Contraintes et risques

| Risque | Gravité | Parade |
| --- | --- | --- |
| Formats non contractuels | Haute | Sondes (D9), état « non pris en charge » visible, fixtures par version |
| Vie privée (service qui lit tout) | Haute | Opt-in par racine, rien lu avant l'accord, indicateur permanent, « lu aujourd'hui », pause, rétention, purge |
| Secrets dans les sorties d'outils | Haute | Expurgation **avant** tout stockage ; seul le résumé est stocké ; aucune source brute n'est resservie ; l'expurgation reste heuristique et c'est dit |
| Injection de prompt entre sessions | Haute | Injection limitée à l'accepté ; activité non revue signalée non fiable ; pas d'acceptation par lot des captures ; plafond quotidien de propositions par projet |
| Données forgées par un programme local | Moyenne | Hook = réveil seul ; preuves relues dans les stores ; limite documentée (même compte = même confiance qu'en v0.1) |
| Chaîne d'installation | Moyenne | Version épinglée, empreinte publiée, tag signé, script lisible |
| Hooks qui cassent un agent | Moyenne | Hook minimal, non bloquant, opt-in, sauvegarde, `uninstall` testé |
| Volume et verrou | Moyenne | Journal par projet, lots courts, budget mesuré |
| Stockage au repos non chiffré | Moyenne | Fichiers lisibles par l'utilisateur seul ; refus des dossiers synchronisés sans confirmation ; chiffrement documenté comme absent (reporté) |
| CGU des applications | Moyenne | Frontière §5 : métadonnées d'identité seulement, aucun contenu de cache de chat ; à faire confirmer |
| Machines multi-comptes | Faible | Données par compte, permissions restrictives ; mono-utilisateur de confiance annoncé |
| Antivirus / EDR | Faible | Ni injection ni hook système ; persistance visible et retirable à la main (documenté) |

---

## 11. Découpage proposé (Windows d'abord)

| Lot | Taille | Contenu | Critères de sortie mesurables |
| --- | --- | --- | --- |
| **V2.0a Installer et tourner** | M | F1, F2, F11, démon `filigree agent`, clé durable, page Couverture, `uninstall` | Installation sur un Windows vierge en < 5 min, 1 seule saisie obligatoire ; après redémarrage, le démon tourne sans console ; `uninstall` laisse 0 artefact (liste vérifiée) ; budget repos respecté |
| **V2.0b Collecter partout** | M | F3, F4, F5 (racines, worktrees prouvés), collecteurs Codex-état et Desktop-Code, **vue Sessions du jour** (agent, projet, début, dernière activité, état) | Sondes D9 passées et consignées ; jeu de 30 sessions synthétiques sur 3 projets et 2 agents : **0** mauvais rattachement, 100 % des sessions hors racine en attente sans texte ; détection < 30 s (p95) |
| **V2.1 Comprendre** | L | F6, F7, F8, F9 chronologie, sous-agents, fiche de session, chevauchements, détection de processus (extra) | 3 terminaux sur un projet et 2 projets en parallèle : 0 fuite ; cas C-1 à C-10 de la revue architecture passés ; fiche de session reproductible (même entrée, même sortie) |
| **V2.2 Transmettre** | M | Hooks opt-in, reprise injectée (accepté seul), outils MCP limités au projet | Un second agent cite une décision acceptée prise dans une autre session ; aucune proposition non revue injectée (test) ; hooks retirés proprement |
| **V2.3 Exports de chat** | S | Boîte de dépôt ChatGPT et claude.ai, rattachement explicite | Export synthétique importé, 0 contenu sans choix de projet |
| V2.x | — | macOS / Linux, modèle local (D3), digest, exécutable empaqueté, icône de notification | Selon décisions |

Dépendances : V2.0a → V2.0b → V2.1 → V2.2. V2.3 ne dépend que de V2.0a.

## 12. Décisions à prendre avec vous

| ID | Question | Recommandation |
| --- | --- | --- |
| D1 | Autoriser des hooks et un enregistrement MCP **opt-in**, ce qui implique d'amender vous-même l'invariant « pas de modification silencieuse » d'`AGENTS.md` ? | Oui en V2.2, avec diff, sauvegarde, retour arrière, portée utilisateur |
| D2 | Journal d'activité SQLite **par projet**, conservé (non jetable), et Markdown pour les connaissances (ADR-0003) ? | Oui |
| D3 | Décisions candidates par modèle : jamais, ou modèle **local** facultatif ? (Le modèle distant est exclu de la V2) | Modèle local facultatif, désactivé, en V2.x |
| D4 | Reprise injectée : uniquement les connaissances acceptées ? | Oui ; l'activité non revue reste disponible à la demande par MCP, signalée non fiable |
| D5 | Distribution : PyPI + script de release, ou exécutable empaqueté ? | PyPI + script en V2.0, exécutable plus tard |
| D6 | Chat (ChatGPT, Claude) limité aux exports et à MCP ? | Oui, annoncé dès l'installation |
| D7 | Détection de processus (`psutil` en extra) ? | V2.1, purement décorative |
| D8 | claude-tap reste-t-il le collecteur principal (ADR-0002 rév. 2) ? On reprend sa **simplicité d'installation**, pas la dépendance à son proxy | Le rétrograder en enrichissement : il cesse d'être un prérequis |
| D9 | Sondes de preuve avant toute promesse de couverture | Obligatoires, consignées dans `.aiwg/testing/` |
| D10 | Rétention du journal par défaut | 90 jours, configurable, purge journalisée |
| D11 | Historique antérieur à l'installation | Aucun rattrapage automatique ; proposé par projet ; sessions archivées exclues |
| D12 | Plateformes | Windows en V2.0, macOS et Linux en V2.x |
| D13 | `auto_create` : créer un projet pour tout nouveau dossier **dans une racine autorisée** ? | Oui dans les racines ; jamais en dehors |
| D14 | Mise à jour des parseurs quand un outil change de format | Sonde au démarrage, source désactivée et signalée, correctif publié dans une version ; aucune lecture approximative |

---

## Annexe A — Sources et observations

**Documentation et sources communautaires (consultées le 17/10/2026) :**
- Claude Code : [hooks](https://code.claude.com/docs/en/hooks), [sessions](https://code.claude.com/docs/en/sessions), [OTel](https://code.claude.com/docs/en/monitoring-usage), [variables](https://code.claude.com/docs/en/env-vars), [statusline](https://code.claude.com/docs/en/statusline).
- Claude Desktop : [stockage, mode 3P](https://claude.com/docs/third-party/claude-desktop/data-storage) ; [antiburn #645](https://github.com/antiburn/antiburn/issues/645) ; [claude-code #57998](https://github.com/anthropics/claude-code/issues/57998), [#48334](https://github.com/anthropics/claude-code/issues/48334) ; export : [takeoutday](https://takeoutday.org/guides/how-to-export-claude-data).
- claude-tap : [README](https://github.com/liaohch3/claude-tap) ; [étude du source v0.1](tap-source-study.md).
- Codex : [configuration avancée](https://learn.chatgpt.com/docs/config-file/config-advanced), [hooks](https://learn.chatgpt.com/docs/hooks), [app-server](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md), [discussion 13251](https://github.com/openai/codex/discussions/13251), issues [20131](https://github.com/openai/codex/issues/20131), [21079](https://github.com/openai/codex/issues/21079), [53503](https://github.com/openai/codex/issues/53503), [format des rollouts](https://dev.to/atoll92/-reading-the-undocumented-session-logs-of-claude-code-codex-and-mistral-vibe-4i67).
- ChatGPT : [MCP / mode développeur](https://help.openai.com/en/articles/12584461-developer-mode-apps-and-full-mcp-connectors-in-chatgpt-beta), [Work with Apps](https://help.openai.com/en/articles/10119604-work-with-apps-on-macos), [CGU](https://openai.com/en-GB/policies/eu-terms-of-use/), [Compliance Logs](https://docs.openlayer.com/integrations/openai-compliance).
- Processus : [psutil](https://psutil.readthedocs.io/), [droits ETW](https://www.geoffchappell.com/studies/windows/km/ntoskrnl/api/etw/secure/index.htm). Les entrées macOS et Linux viennent de connaissances générales [?].

**Observations locales [O] (noms de champs uniquement) :**
- `~/.codex/state_5.sqlite` `threads` : `id, rollout_path, cwd, source, model, cli_version, git_sha, git_branch, git_origin_url, agent_nickname, agent_role, tokens_used…`. `source` vu : `cli`, `exec`, `vscode`, objet `subagent.thread_spawn{parent_thread_id, depth…}`. Tables `thread_spawn_edges`, `projects`, `project_roots`.
- `~/.codex/thread_history_1.sqlite` : `thread_turns`, `thread_items`. `session_index.jsonl` : `id, thread_name, updated_at`. Présence de `hooks.json` et `app-server-daemon/`.
- `%APPDATA%/Claude/claude-code-sessions/**/local_<uuid>.json` : `sessionId, cliSessionId, cwd, originCwd, model, title, createdAt, lastActivityAt, isArchived…`.
- `~/.claude/projects/*/*.jsonl` : `sessionId, cwd, gitBranch, entrypoint, isSidechain, version, parentUuid, timestamp…`.
- Paquets MSIX `Claude_pzs8sxrjxfjjc` et `OpenAI.Codex_2p2nqsd0c76g0` ; claude-tap `~/.local/share/claude-tap/traces.sqlite3`.
