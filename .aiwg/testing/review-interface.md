# Revue indépendante — interface, parcours et contrat produit

Date : 15 octobre 2026. Relecteur : agent interface. Artefacts relus : `requirements/vision.md`, `requirements/user-stories.md`, `architecture/ADR-0001-local-portable-memory.md`. Cette revue est une lecture indépendante de ces artefacts, pas une exécution de tests. Les tests navigateur et de domaine restent confiés à l'orchestrateur.

## Avis

⚠️ Favorable au socle proposé, sous réserve de rendre les critères cohérents avec le modèle réellement livré et de conserver les limites visibles dans le gate. L'architecture locale, le Markdown canonique, les statuts explicites et l'absence de dépendance à un modèle rendent le produit défendable. La démo de recadrage est un meilleur critère que la promesse générale de « mémoire intelligente ».

## Écarts à traiter par la synthèse

1. **US-01 : épisode autonome non représenté.** Le modèle et l'interface utilisent un champ `episode` libre sur les connaissances. Ils ne créent pas un objet épisode avec objectif et identifiant propre. La story demande davantage que le contrat actuel. Décrire honnêtement le regroupement par libellé de v0.1 et conserver l'entité autonome comme évolution, ou implémenter cette entité avant de déclarer US-01 satisfaite.
2. **US-03 : raison de revue.** Le corps d'une connaissance peut contenir les raisons et reste versionné. Les actions rapides Accepter/Écarter changent le statut ; elles n'imposent pas une raison indépendante. Le critère « conserve […] la raison saisie » doit être précisé : justification dans le contenu, ou nouveau champ/action de revue. Ne pas prétendre qu'une justification a été collectée lorsqu'elle ne l'a pas été.
3. **Historique lisible contre historique consultable.** L'interface affiche les événements et numéros de révision. Les snapshots historiques sont des fichiers canoniques mais la consultation du contenu d'une ancienne révision dans le navigateur demande une route dédiée. Le terme « historique lisible » doit nommer le canal de consultation effectivement livré.
4. **Reprise et alternatives.** La vision exige de conserver les pistes écartées et le cheminement. Leur inclusion dans une section historique explicitement non actuelle est nécessaire ; les exclure toutes de la reprise ferait perdre une partie essentielle de la valeur annoncée. L'orchestrateur a annoncé cette correction ; le gate doit vérifier le résultat réel.

## Décisions d'interface conformes à l'ADR

- Les statuts apparaissent sous forme de texte, pas seulement de couleur ; « acceptée » n'est jamais affiché comme « prouvée ».
- Le remplacement est une nouvelle connaissance acceptée avec relation `supersedes`, pas un effacement. L'action Remplacer prépare cette relation ; le serveur reste l'autorité de validation.
- Les sources ont des champs nom, extrait et référence ; les relations utilisent des sélecteurs. Aucun JSON n'est requis dans les parcours humains ordinaires.
- Les textes des connaissances et sources sont échappés avant insertion ; les liens cliquables sont limités aux protocoles HTTP(S). Les autres références restent du texte.
- La navigation comprend liste/recherche, chronologie, graphe, reprise et import. Les nœuds du graphe sont accessibles au clavier et ouvrent la même fiche que la liste.
- Les importations texte/Markdown deviennent des propositions explicites, sans interprétation automatique présentée comme une compréhension acquise.
- Les vues vides, erreurs réseau, erreurs de saisie et absence de Git ont un message et une action compréhensibles.
- La fiche de reprise peut contenir des données du projet : le parcours indique ce point avant un transfert à un agent externe, sans envoyer automatiquement les données.

## Vérifications à faire au gate

Exécuter les parcours création → sources → acceptation → remplacement → détail historique → reprise, puis import texte et JSONL → réimport sans doublons. Vérifier l'affichage sur écran étroit, le focus des dialogues, les erreurs de concurrence et l'absence d'exécution de HTML importé. Cette revue ne remplace aucun de ces contrôles.

## Suite donnée pendant l'intégration

Les points 2 et 3 ont entraîné des changements : Accepter/Écarter ouvre désormais une saisie de justification facultative ; l'édition permet également une raison de révision. Les événements affichent cette justification. La fiche charge les snapshots historiques via l'API et permet de consulter chaque ancien contenu, statut et ensemble de sources. Ces implémentations réduisent les écarts identifiés ; leur validation d'exécution demeure à consigner par l'orchestrateur.
