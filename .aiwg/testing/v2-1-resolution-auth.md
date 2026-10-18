# V2.1 — résolution confinée et clé locale : preuves d'exécution

Date : 17 octobre 2026. Exécutant : orchestrateur (Opus), poste Windows 10, Python 3.14. Référence : [ADR-0003](../architecture/ADR-0003-permanent-observer.md), sections « Réglages », « Clé locale et API », « Résolution ».

## Changements couverts

| Incrément | Commit | Contenu |
| --- | --- | --- |
| Collecteurs, sonde, ADR-0003 | `136d391` | Cinq collecteurs en lecture seule, `probe.py`, `resolver.py` (non branché à ce stade), tests synthétiques |
| Résolution | `c7c68b9` | `allowed_roots` (`null` = v0.1 ; liste ⇒ `outside_roots`, clé seule, aucun projet créé) ; worktree prouvé dans les deux sens ⇒ projet du dépôt principal, `worktree_of` dans la provenance |
| Clé locale | ce commit | `<data-dir>/.runtime/agent.key` créé une fois (`O_EXCL`), partagé par les serveurs d'un même dossier ; clé corrompue refusée, jamais remplacée ; jeton exigé sur **toute** route `/api/*`, lectures comprises, sauf `GET /api/bootstrap`, qui ne renvoie plus la liste des projets |

## Commandes exécutées et résultats réels

| Commande | Résultat |
| --- | --- |
| `python -m unittest discover -s tests` | 330 tests OK, 1 ignoré (POSIX) |
| `node --check filigree/static/app.js` | OK |
| `npm test` (Playwright, Chromium) | 28 réussis (1,8 min) après adaptation de `final.spec.cjs` |
| `python -m pip wheel . --no-deps --wheel-dir .runtime/wheels` | OK ; le wheel contient `filigree/collectors/*`, `probe.py`, `resolver.py` |
| `python scripts/verify_package.py` | PASS (installation isolée, version CLI, HTML/JS, bootstrap local) |

Le premier passage Playwright a donné 27 réussis et 1 échec : `final.spec.cjs:154` lisait `/api/projects` sans clé. C'est la conséquence attendue de S-06 ; le test récupère maintenant la clé par le bootstrap. Deux tests Python (`test_remediation_services`) ont été adaptés pour la même raison. L'exécution Playwright régénère `.github/assets/workbench.png` ; ce fichier a été restauré et n'est pas committé.

## Tests ajoutés

- `test_capture.AllowedRootsAndWorktreeTests` (6) : session hors racine en attente sans texte ; la racine prime sur un projet existant ; `null` conserve la v0.1 ; réglage malformé ⇒ capture désactivée ; worktree prouvé rattaché ; lien `gitdir` non réciproque non suivi.
- `test_http` (3) : toute lecture API exige la clé ; clé persistante et partagée (permissions `0600` vérifiées hors Windows) ; clé corrompue refusée et laissée intacte.

## Limites restantes

- Sous Windows, `agent.key` hérite des ACL du dossier de données : aucune restriction propre (documenté dans `SECURITY.md`). Tout processus du même compte peut lire la clé.
- `allowed_roots` ne s'édite que dans `capture.json` : `filigree setup` (qui doit l'écrire) n'existe pas encore.
- Pas encore implémentés : démon `filigree agent`, `service.py`, journal d'activité, distillation, `filigree probe`/`status` en CLI, V2.2 (MCP restreint, hooks), V2.3 (imports de chat).
- Aucune relecture indépendante de ces deux incréments ; aucun appel live exécuté.
- macOS et Linux ne sont pas exécutés ici (D12 : tests synthétiques seulement).
