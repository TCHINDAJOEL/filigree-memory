> Historique : ce rapport a été invalidé par les vérifications exploratoires ultérieures. Consulter [l'exécution actuelle](release-execution.md) et le [gate courant](../deployment/release-gate.md).

# Vérification finale — Filigree 0.1

Date : 16 octobre 2026. Exécuteur : Claude Haiku via claude-tap. Synthèse : orchestrateur Codex. Ce rapport remplace les états intermédiaires pour la décision de livraison ; les anciens rapports restent conservés.

| Contrôle | Résultat exécuté | Preuve / périmètre |
| --- | --- | --- |
| Suite Python | **140 tests, OK** | Domaine, dossiers, capture, crash entre fichiers, pause, isolation, imports, Git, MCP, HTTP, runner quota |
| Parcours Playwright | **7 réussis** | Gouvernance, reprise historique, graphe, HTML inerte, mobile, brouillons, sélection de projet et contrôles de capture |
| JavaScript | Syntaxe valide | `node --check filigree/static/app.js` |
| Distribution | Wheel construit et installation isolée **PASS** | CLI, ressources statiques et bootstrap HTTP hors dépôt, serveur sans capture |
| Claude Code via TAP, réel | **PASS** | Dossier créé automatiquement, 3 propositions, marqueur et provenance exacts, absence de doublon au rescan |
| Claude Code direct, réel | **PASS** | Sans TAP : 4 propositions, dossier natif exact, marqueur présent, provenance native et déduplication |
| Reprise par un vrai client MCP | **PASS** | Haiku appelle les outils Filigree, reçoit les notes et cite correctement choix actuel, choix remplacé et question ouverte avec leurs identifiants ; aucun statut modifié |

Les preuves d'exécution détaillées sont privées : `queue-6-result.txt` pour navigateur/paquet/TAP, `targeted-tests-result.txt` pour la suite finale et le lancement direct, `mcp-pass-result.txt` pour MCP. Elles ne sont pas publiées car elles contiennent des métadonnées locales. Les commandes reproductibles sont dans AGENTS.md et les scripts publics. Les comptes et sorties OK/PASS sont les preuves : l'interface Bash du testeur n'affichait pas toujours le code numérique de sortie.

## Échecs corrigés, sans suppression de contrôle

- Validation de `dossier-manquant/..` sous Windows ; brouillon de capture effacé lors d'un rafraîchissement ; sélection asynchrone de projet.
- Sauvegarde des clés en attente avant l'avancement des curseurs : panne injectée entre les deux écritures, puis reprise et rattachement.
- Préservation des lignes natives retenues avant pause, séparation des réglages de repli et de la capture TAP, rattachements TAP propres à la base.
- Ajout Git par blocs bornés, historique avec deux rattachements concordants, protection des brouillons d'import lors d'un changement de projet.
- Assertion de tri corrigée sans modifier le comportement du produit ; validation de provenance native distinguant ses sources auxiliaires documentées.
- Le test MCP héritait du mode safe du testeur (`CLAUDE_CODE_SAFE_MODE=1`). Sa session enfant isolée retire ce marqueur, utilise seulement sa configuration MCP explicite, désactive hooks/skills et ne permet que les outils de lecture. Les configurations de l'utilisateur et les politiques administrées restent intactes. L'essai finalement exécuté prouve la récupération réelle, pas seulement le transport JSON-RPC.
- Le runner reconnaît désormais l'erreur structurée `usage_limit_reached` et le libellé « session limit ». La régression est incluse dans les 140 tests.

Les derniers correctifs ne modifiaient que les assertions et les helpers de tests ; les résultats navigateur et paquet portent sur le même code produit final, sans réexécution inutile.

## Limites de la preuve

Les clients réels essayés sont Claude Code/Haiku sur cette machine. Codex dispose de fixtures et de tests d'isolation et de partage de dossier ; aucun essai réel Codex CLI/App n'est revendiqué. Un client doit être raccordé à MCP et demander la mémoire : aucune injection universelle automatique n'est démontrée. Le moniteur doit tourner ; l'installateur de démarrage Windows n'a pas été exécuté. Les captures deviennent des propositions à examiner, sans synthèse LLM automatique ni accès au raisonnement caché. Les performances à grande échelle ne sont pas mesurées. La CI GitHub sera constatée séparément après publication.
