# Filigree — plan de livraison et limites

Date : 15 octobre 2026. Auteur et synthétiseur : agent produit/architecture. Statut : plan révisé après revues, à actualiser avec les preuves de l'orchestrateur. Adaptation du modèle AIWG `templates/management/iteration-plan-informal-template.md`. Voir [la synthèse](../testing/review-synthesis.md).

## Objectif

Livrer une première version présentable et défendable : un nouvel arrivant peut comprendre une histoire de projet, corriger sa mémoire et reprendre son travail avec les sources nécessaires. « Livré » signifie utilisable et vérifié dans son périmètre annoncé ; cela ne signifie pas que toute la vision future existe déjà.

## Organisation et jalons

| Responsabilité | Périmètre | Dépendance / contrôle |
| --- | --- | --- |
| Chef d'orchestre / intégration | Contrats communs, serveur, CLI, MCP, GitHub | Accepte les livrables après preuves |
| Produit / architecture | Vision, stories, ADR, limites et recherche | Revue métier et technique indépendante |
| Domaine / stockage | Épisodes, connaissances, statuts, imports, export, historique | Invariants communs à toutes les interfaces |
| Interface | Navigation, gouvernance, recherche, graphe, reprise | Contrats du domaine ; inspection visuelle |
| Testeur | Exécution des scénarios et rapport fidèle | Séparé des affirmations de l'auteur |
| Vérificateurs | Revue des écarts produit, sécurité et maintenabilité | Deux avis indépendants, puis synthèse |

L'auteur produit un artefact, les reviewers examinent en parallèle, le synthétiseur résout les remarques et l'orchestrateur archive dans `.aiwg/`. Quatre agents au plus sont actifs simultanément ; les rôles de revue peuvent être pris successivement une fois les implémentations terminées. Claude Code peut être sollicité via `claude-tap` après vérification locale de son fonctionnement. Les exécutions de tests déléguées suivent le routage Haiku demandé par l'utilisateur lorsqu'il est effectivement disponible ; une indisponibilité doit être signalée, pas remplacée silencieusement.

| Jalon | Critère de passage | État initial |
| --- | --- | --- |
| Cadrage | Vision, stories, ADR et contrats cohérents | ✓ Auteur, deux revues indépendantes et synthèse ; gate restant |
| Boucle utile | Import → proposition → gouvernance → reprise sur disque | ⏳ Réalisation |
| Interface intégrée | Parcours démontrable, erreurs compréhensibles, graphe relié aux notes | ⏳ Réalisation |
| Vérification | Rapport des tests et revue des risques ; aucun défaut critique ouvert | ⏳ À effectuer |
| Publication | Installation documentée, exemples publics propres, licence, CI, dépôt vérifié | ⏳ À effectuer |

Aucune transition de phase n'est attestée par ce tableau seul. L'orchestrateur effectue le gate sur les artefacts et preuves effectives avant de déclarer la livraison prête.

## Périmètre v0.1 engagé

- Application locale et données de démonstration explicites.
- Projet identifié avec description d'objectif ; notes typées regroupées par libellé d'épisode, propositions et décisions, raisons et sources.
- Gouvernance explicite : accepter, rejeter, remplacer et garder l'histoire.
- Capture automatique par dossier (mise à jour du 16 octobre 2026 : [ADR-0002](../architecture/ADR-0002-automatic-project-capture.md), US-11 à 16) : moniteur local, base claude-tap lue en lecture seule, transcriptions natives pour les lancements directs, propositions avec provenance. L'import manuel des formats documentés et la surveillance CLI d'un fichier choisi demeurent en récupération ; recherche textuelle et graphe de liens explicites. Aucune interception d'application, aucune extraction sémantique ni pensée cachée.
- Fiche de reprise Markdown distinguant courant, incertitudes et historique ; MCP de lecture/proposition ; fichiers canoniques portables. Aucun lanceur d'agents intégré.
- Checkpoints Git limités au périmètre mémoire. Originaux externes non archivés automatiquement ; extraits de source inclus dans la mémoire exportable.
- Documentation d'installation, de contribution, d'architecture et de limites ; tests adaptés ; démonstration du recadrage Basic Memory.

## Après v0.1 : hypothèses à évaluer

| Évolution | Pourquoi attendre | Condition pour investir |
| --- | --- | --- |
| Épisode autonome identifié | v0.1 utilise un libellé partagé entre notes | Besoin d'objectifs, états et relations propres à chaque épisode |
| Capture continue étendue (autres clients, hooks, Claude Desktop, Claude web) | La capture par dossier couvre Claude Code et Codex via claude-tap et leurs transcriptions locales ; le reste n'est pas couvert | Sources locales stables, gestion des erreurs et secrets, vrais essais par client |
| Synthèse automatique par modèle | Risque de transformer une suggestion en vérité | Corpus annoté, provenance, abstention, mesure de fidélité |
| Recherche sémantique | Coût et dépendances avant de connaître la limite du texte | Échecs de recherche observés et benchmark utile |
| Détection de contradictions | Une proximité de texte n'est pas une contradiction | Propositions explicables, confirmation humaine |
| Procédures personnelles interprojets | Une occurrence n'est pas une préférence générale | Plusieurs exemples, portée et validation explicites |
| Collaboration distante | Change le modèle de sécurité et concurrence | Besoin réel, authentification, autorisations et transactions |

## Démonstration et critères de sortie

1. Ouvrir une mémoire de démonstration avec objectif, connaissances sous un même libellé d'épisode et plusieurs alternatives.
2. Montrer une source, une proposition, une décision et une tentative écartée.
3. Enregistrer un recadrage puis examiner sa relation à l'ancien choix.
4. Lire la fiche de reprise : le choix suspendu reste suspendu.
5. Montrer les mêmes connaissances dans les fichiers et via MCP.
6. Montrer les résultats réellement exécutés et les limites connues avant de présenter le dépôt.

Critères de sortie : instructions reproductibles, aucun secret ni trace privée dans le dépôt logiciel, stories reliées aux tests réels, limites visibles, revues synthétisées, publication GitHub vérifiée ou blocage factuel expliqué. Les performances et bénéfices utilisateurs non mesurés ne deviennent pas des promesses marketing.
