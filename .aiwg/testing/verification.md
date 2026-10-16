# Vérification — journal de preuves

**Rapport courant : [exécution après corrections](release-execution.md).** Les sections ci-dessous sont historiques. La vérification exploratoire indépendante a invalidé le premier GO ; consulter le [gate courant](../deployment/release-gate.md) pour la décision de livraison.

Statut : **en cours**. Ce rapport ne constitue pas encore un gate de livraison.

## Résultat le plus récent — 16 octobre 2026, vers 01:00 Paris

Exécution indépendante par Claude Haiku via `claude-tap`, après correction des deux échecs de la passe précédente. Rapport privé `.runtime/queue-3-result.txt`. Aucun changement de code par le testeur.

| Contrôle exécuté | Résultat |
| --- | --- |
| Suite Python complète | **130 tests, OK**, 34,98 s |
| Syntaxe JavaScript | Aucune erreur |
| Construction wheel | `filigree_memory-0.1.0-py3-none-any.whl` produit |
| Installation isolée hors dépôt | **PASS** : version CLI, HTML/JS embarqués, bootstrap HTTP |
| Playwright | **6 parcours réussis**, 34,2 s |
| Capture réelle Claude Code via TAP | **PASS**, un appel Haiku de 6,3 s, sans répétition |

Le contrôle réel a utilisé un dossier synthétique, une base TAP séparée et un index natif isolé alimenté uniquement par les métadonnées de la session créée. L'identifiant de la trace correspond à l'identifiant natif ; le projet est créé pour le dossier attendu ; trois observations restent proposées, dont deux contiennent le marqueur de test ; les sources concordent et un second scan ne crée aucun doublon. Les diagnostics bruts restent privés. Cela prouve une invocation Claude Code sur cette machine, pas toutes les versions ni le fonctionnement réel de tous les clients Codex.

Les six parcours navigateur couvrent la gouvernance et la reprise historique, la démo et l'affichage de HTML hostile, le rendu mobile, la conservation des formulaires pendant le rafraîchissement, le changement de projet en cours de requête et les contrôles de capture. Le test du panneau de capture utilise aussi des réponses synthétiques ; le contrôle réel séparé vérifie la chaîne TAP → dossier → mémoire.

Les serveurs de tests utilisent `--no-capture` et des chemins TAP isolés. Avertissements restants : annonce de mise à jour pip et conflit de variables de couleur du terminal, sans échec. Les sorties PASS/OK et comptes sont les preuves ; certains appels outils du testeur n'affichaient pas explicitement le code de sortie numérique.

**Réserves encore ouvertes :** la revue indépendante Opus a eu lieu depuis (source seulement, `review-capture-opus.md`) ; ses constats, dont RC-07, ont reçu des corrections **en source, non exécutées** : voir [final-fixes.md](final-fixes.md). Les résultats ci-dessus portent sur le code *avant* ces corrections ; suite, Playwright, wheel et `verify_package.py` sont à refaire. La CI GitHub et la compréhension réelle d'une reprise par un autre modèle ne sont pas encore vérifiées. Les sections suivantes conservent l'historique des passes antérieures.

## Socle avant capture automatique

Exécution par Claude Haiku via `claude-tap`, le 16 octobre 2026 (heure de Paris). Rapports techniques détaillés privés dans `.runtime/`, non publiés car ils peuvent contenir des métadonnées de session.

| Vérification | Résultat observé |
| --- | --- |
| `python -m unittest discover -s tests -v` | 45 tests réussis ; avertissement de fermeture du verrou du runner à corriger |
| `node --check filigree/static/app.js` | Aucune erreur de syntaxe |
| Construction wheel | `filigree_memory-0.1.0-py3-none-any.whl` produit |
| Installation isolée du wheel | CLI, HTML/JS embarqués et bootstrap HTTP vérifiés |
| Parcours navigateur gouvernance/reprise | Réussi après correction de la soumission de formulaire |
| Parcours navigateur démo/HTML hostile/mobile | Échec sur sélecteur de bouton ; sélecteur corrigé, réexécution nécessaire |

Le défaut réel de formulaire venait du champ nommé `id`, qui masquait la propriété DOM `form.id`. La soumission utilise désormais `getAttribute('id')`. Le second échec concernait un nom accessible incluant « + » ; le bouton est ciblé par son identifiant stable. Aucun test n'a été supprimé pour obtenir un résultat favorable.

## Extension d'activation automatique

Les résultats du socle ne valident pas cette extension.

**Exécuté (Haiku via claude-tap, 16 octobre 2026, avant les corrections ci-dessous ; rapport privé `.runtime/queue-1-result.txt`)** : `python -m unittest discover -s tests -v` — 124 tests, 1 échec (`test_folders.FolderTests.test_canonical_folder_requires_an_existing_absolute_directory` : `…\nope\..` accepté) ; `node --check` sans erreur ; wheel construit ; `verify_package.py` PASS ; Playwright — 5 réussis, 1 échec (`workbench.spec.cjs` « capture view … maps a pending session » : le champ « Dossier à exclure » est vidé). Le contrôle live était en attente (script absent).

**Corrections apportées après ce rapport — contrôles de source uniquement, NON exécutés** :
- `store.canonical_folder` refuse un chemin dont un dossier précédant `..` n'existe pas (Windows réduit `manquant\..` avant de tester l'existence).
- `app.js` : `render()` ne reconstruit plus la vue Capture déjà affichée (le rafraîchissement lancé après un rattachement effaçait les formulaires) ; le serveur ignore une déconnexion du navigateur en cours de réponse au lieu d'afficher un second échec.
- Rattachements `tap:ID` liés à la base claude-tap choisie ; transcription native non résolue retenue à son décalage (au plus 100 fichiers), exposée en attente sans texte, relue dans l'ordre ; pause et exclusion restent des sauts délibérés.
- Tests ajoutés : `HeldNativeTests` (4), `ScopedMappingTests` (2) dans `tests/test_capture.py`.
- Capture d'écran du README produite par le test navigateur vers `.github/assets/workbench.png`.

**À exécuter** (rien ci-dessus n'est prouvé tant que ce n'est pas fait) : suite Python complète, `node --check`, Playwright, reconstruction du wheel puis `verify_package.py` (F-PACKAGE-01), puis, avec accord explicite, `python -X utf8 scripts/verify_live_capture.py` (un seul appel Claude Haiku, 300 s, base et mémoire isolées ; prouve un client sur une machine, pas la couverture générale). `--check-only` vérifie l'isolation sans appel.

La CI est configurée mais aucun résultat GitHub Actions n'est encore revendiqué. La preuve de compréhension d'un vrai deuxième modèle est distincte des échanges JSON-RPC MCP et devra être signalée séparément si réalisée.
