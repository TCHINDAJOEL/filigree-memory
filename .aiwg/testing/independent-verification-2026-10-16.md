# Vérification indépendante — Filigree 0.1

Date : 16 octobre 2026. Orchestrateur : Claude Opus (Claude Code). Testeurs : cinq agents Claude Sonnet indépendants, à la demande de l'utilisateur (le routage Haiku est remplacé pour cette session). Ce rapport ne remplace pas [final-verification.md](final-verification.md) ni [release-review.md](release-review.md), qui restent l'historique. Il en **révise la conclusion**.

## Conclusion

**Le GO de `release-review.md` ne tient plus.** Les suites existantes passent, mais l'exécution exploratoire montre :
- 1 défaut P1 de confidentialité, confirmé en réel ;
- environ 30 défauts P2 ;
- de nombreux défauts P3.

Aucun de ces défauts n'est couvert par les 140 tests ni par les 7 parcours Playwright. La publication publique doit attendre la correction au minimum du P1 et des P2 marqués « bloquant ».

## 1. Base exécutée (orchestrateur)

| Contrôle | Résultat |
| --- | --- |
| `python -m unittest discover -s tests` | 140 tests, OK, code 0 |
| `node --check filigree/static/app.js` | code 0 |
| `npm test` (Playwright) | 7 réussis, code 0 |
| `pip wheel` + `scripts/verify_package.py` | PASS, code 0 |

## 2. Tests réels (agent E, 6 appels Claude Haiku)

| Commande | Code | Résultat |
| --- | --- | --- |
| `verify_live_capture.py --check-only` / `verify_live_handoff.py --check-only` | 0 / 0 | PASS |
| `verify_live_capture.py` (TAP) | 0 | PASS : 3 propositions, provenance exacte |
| `verify_live_capture.py --native-direct` | 0 | PASS : 4 propositions, pas de doublon |
| `verify_live_handoff.py` | 0 | PASS : 3 identifiants cités exactement |

Parcours réel hors scripts :
1. Une vraie session `claude -p --model haiku` dans un dossier de test énonce une décision.
2. La capture crée le projet et 2 propositions en 23 s, avec la provenance exacte.
3. Playwright accepte la décision dans l'UI ; la fiche de reprise l'affiche comme courante.
4. Une seconde session Claude, branchée en MCP (lecture seule), **ne retrouve pas la décision** (E-2).
5. Un essai avec de faux secrets montre une URL `postgres://u:motdepasse@…` stockée et affichée en clair (E-1 = B-1).

## 3. Défauts

Les rapports détaillés, avec les scripts de reproduction, sont dans le scratchpad de la session (non publié) :
- agentA : stockage, imports, Git, démo ;
- agentB : capture ;
- agentC : HTTP, MCP, CLI ;
- agentD : interface réelle ;
- agentE : test réel.

« Bloquant » désigne ce qu'il faut corriger avant toute publication publique.

### P1

| ID | Défaut | Lieu présumé |
| --- | --- | --- |
| B-1 / A-6 / E-1 | **Masquage des secrets incomplet.** Restent en clair : `X_API_KEY=` / `DB_PASSWORD=` (`\b` échoue après `_`), URL avec identifiants, AWS, Slack, Google, Stripe, JWT, `Authorization: Basic`, `client_secret`, mots de passe entre guillemets échappés. `"password": "x y z"` ne masque que le premier mot. Confirmé en réel. | `store.py:28-34` |

### P2 bloquants

| ID | Défaut | Lieu présumé |
| --- | --- | --- |
| C-4 / D-12 | `POST /api/capture start` démarre la capture sur un serveur `--no-capture`, et elle lit les sources réelles par défaut. Pendant le test, 52 transcriptions réelles de l'utilisateur ont été importées dans un dossier de test local, non publié et conservé à sa demande. La vue Capture lit la vraie base TAP même en `--no-capture`. | `server.py` capture_action |
| E-2 | `get_handoff(query=…)` sans correspondance lexicale renvoie seulement l'objectif, avec `excluded: 0`. Un vrai agent conclut qu'aucune décision n'existe. `search_memory("database")` ne trouve pas un texte qui parle de SQLite ou de Postgres. | `store.py` handoff/search |
| B-2 | Un message qui commence par `<system-reminder>`, `<ide_selection>` ou `<environment_context>` est entièrement perdu, y compris la question de l'utilisateur. | `tap_source.py` visible_text ~187 |
| B-3 | Un dossier au nom de plus de 160 caractères bloque à chaque cycle la capture de toutes les sessions suivantes (`ValueError` non interceptée). | `capture.py` ~561 |
| B-7 / A-14 | Des projets sont créés automatiquement pour `%TEMP%`, `C:\Users` et `C:\Windows`. Tous les dossiers sous `%TEMP%` sont fusionnés dans le projet « Temp ». | `capture.py` ~555-575, `store.py` canonical_folder |
| A-3 | Un seul fichier égaré ou abîmé (README dans `entries/`, BOM, titre modifié, `project.json` invalide) casse `projects`, `handoff` et `export` pour tous les projets. | `store.py` _entries, list_projects |
| A-8 | Une entrée acceptée qui en remplace une rejetée ou non examinée la passe à `superseded` sans validation humaine. L'opération est irréversible. | `store.py` _supersede |
| C-1 | MCP lit stdin en cp1252 : accents et emoji abîmés, dossier non ASCII introuvable. | `cli.py` / `mcp.py` |
| C-3 | `mcp-config --client codex` produit un TOML invalide (`\r\r\n`). | `cli.py` |

### Autres P2

- **Capture**
  - **B-4** : `capture link file:…` répond `replayed: true` sans effet.
  - **B-5 / B-6** : les lignes contenant `\u0000`, un surrogate isolé ou de l'UTF-8 invalide sont perdues sans aucun compteur.
- **Imports**
  - **A-1** : un enregistrement de plus de 100 000 caractères fait échouer tout l'import, et `watch` boucle.
  - **A-2** : au-delà de 1000 enregistrements, l'import échoue, et `watch` boucle aussi.
  - **A-7** : un message identique répété est compté comme doublon. Une entrée supprimée ne peut plus être réimportée.
- **Stockage**
  - **A-4** : un même dossier peut être lié à deux projets, sous les formes `C:\x` et `\\?\C:\x`.
  - **A-5** : chaque opération est en O(N). À 3000 entrées, une écriture prend 4,8 s et l'export 15,5 s.
- **Serveur** : **C-2** : sur Windows, deux `serve` peuvent écouter le même port (`allow_reuse_address`).
- **Interface**
  - **D-1** : la fiche ne se rafraîchit pas après « Remplacer ». Les relations entrantes ne sont jamais affichées, ce qui contredit US-04.
  - **D-2** : en cas de conflit d'édition, l'erreur est en anglais et rien ne permet de recharger.
  - **D-3** : la recherche est sensible aux accents.
  - **D-4** : à 375 px, le bouton Git est inaccessible, des éléments se chevauchent et des onglets sont hors écran.
  - **D-5** : un projet créé par la capture n'apparaît qu'après rechargement de la page.
  - **D-6 / E-4** : une entrée native est étiquetée « claude-tap », « 4 sources » s'affiche pour un seul message, et du JSON brut est visible.
  - **D-7** : Échap ferme le formulaire et perd le brouillon.

### P3 (résumé)

- **Messages et sorties** : messages d'erreur bruts ou en anglais (`'Project not found'`, exceptions Python, tracebacks sur schémas inattendus) ; fiche de reprise entièrement en anglais, avec des UUID au lieu des titres.
- **Interface** : graphe illisible au-delà de quelques centaines de nœuds ; libellés incohérents ; état périmé (toast, erreur d'import) ; aucun indicateur d'occupation.
- **Capture** : `demo` non idempotent ; `watch` fragile ; `--interval nan|inf` ; un nouveau fichier `.jsonl` est importé en entier (contredit « futur uniquement ») ; compteur `redactions` toujours à 0.
- **Gouvernance et MCP** : un processus local peut créer une entrée déjà `accepted` en HTTP ; MCP accepte `agent:"human"` et un corps vide.
- **Git** : statut avec chemins octaux et `dirty` permanent.
- **Configuration** : `mcp-config` suppose le paquet installé.

## 4. Ce qui fonctionne (confirmé par exécution)

- **Sécurité HTTP** : contrôles Host, Origin et jeton ; écoute en boucle locale uniquement ; CSP ; HTML neutralisé partout ; environ 110 requêtes d'erreur renvoient des codes 4xx propres.
- **Robustesse** : concurrence correcte (6 processus, aucune perte ; acceptations parallèles 1 × 200 et 7 × 409) ; reprise après 25 `kill -9` cohérente.
- **Gouvernance** : les imports et les captures restent des propositions ; la reprise distingue courant, incertain et historique ; MCP en lecture n'écrit jamais.
- **Capture**
  - Contrôles : pause, exclusion, repli, verrou et redémarrage ; le raisonnement caché n'est jamais capturé.
  - Délais : 22-28 s en natif, 3 s en TAP.
  - Rattachement : dossier vers projet, isolation entre dossiers, même projet pour Claude et Codex.
- **Git** : l'allowlist n'ajoute jamais de fichier étranger.
- **Interface** : premier lancement clair ; navigation clavier et focus corrects ; brouillon d'import protégé au changement de projet.
- **Tests réels** : les trois scripts réels passent.

## 5. Limites de cette vérification

- Aucun essai réel avec Codex.
- Aucun essai réel des données TAP en streaming (SSE).
- Lecteurs d'écran, remote/push Git et installateur de démarrage Windows non testés.
- Mesures sur une seule machine (le coût des `open()` est probablement lié à l'antivirus).
- L'agent C est sorti de son périmètre d'isolation en démarrant la capture via l'API. Le moniteur a été confirmé arrêté et les données sont restées locales.
- Les rapports des agents ont été transcrits par l'orchestrateur, car leurs écritures de fichiers ont été refusées.
