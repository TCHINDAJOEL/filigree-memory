# Synthèse finale du guide utilisateur

17 octobre 2026. Livrable : `livrables/Guide_utilisation_Filigree.docx` (19 pages, 11 figures). Texte extrait : `.aiwg/deployment/guide-utilisation-final.md`. Le brouillon `.aiwg/deployment/guide-atelier-content.md` est marqué remplacé. Produit inchangé.

## Méthode

Corrections appliquées par l'orchestrateur dans `word/document.xml`, sans toucher aux figures ni aux styles. Après chaque passe : validation XSD réussie, puis export PDF par Word (19 pages) et contrôle visuel des pages modifiées. Deux relecteurs indépendants (Claude Haiku, lecture seule, sans exécution) ont relu la première passe. Leurs constats retenus ont été intégrés dans une seconde passe, qui n'a pas été relue à nouveau.

Faits revérifiés dans le code ou les données de l'atelier :

- budget de 500 à 100000 (`cli.py`, `mcp.py`) ;
- libellé « Historical alternatives — NOT CURRENT » (`store.py`) ;
- schéma claude-tap 4 (`tap_source.py`) ;
- commandes `capture fallback on|off` et `capture link KEY PROJECT_ID` (`cli.py`) ;
- raison de révision facultative et libellés des fenêtres « Accepter cette connaissance » et « Écarter cette proposition » (`app.js`) ;
- push limité aux dépôts distants GitHub (`git_sync.py`) ;
- note sur le délai de 24 ou 48 h (Atlas) ;
- quatre identifiants cités par Haiku (`repreneur-result.json`) ;
- états des 14 notes (Atlas 4, Agora 4, Orion 6).

## Défauts de la revue d'exactitude initiale

| # | Statut |
|---|---|
| 1 Proposition de l'architecte | Corrigé : notes acceptées nommées, §7 en observation pour Atlas livré, étape 1 renvoyée à la proposition de l'Essai |
| 2 Repli natif | Corrigé (déjà présent avant cette session, revérifié) |
| 3 Graphe et Reprise Orion | Corrigé : ligne scindée, graphe « Vérifié (interface) », Reprise Orion et nouvel agent « Non exécuté » |
| 4 « 24 ou 48 heures » | Corrigé : rattaché à la note « Quel délai pour retirer une réservation » |
| 5 Raison facultative | Corrigé |
| 6 Schéma 4 | Corrigé |
| 7 Projet sans dossier et `capture link` | Corrigé, avec la définition des paramètres |
| 8 Plage de budget | Conservée, vérifiée dans le code |
| 9 Corps importé copié | Corrigé |
| 10 Bilan | Corrigé : défaut du harnais, pas du produit ; Agora vérifié ensuite, sans nouvel appel |

## Défauts de la revue pédagogique initiale

Points 1, 2, 4, 5 et 7 corrigés. Point 3 corrigé : mode observation en §6, §7, §9 et §10, titres exacts des trois notes à recopier. Point 6 corrigé : statuts normalisés en « Vérifié (interface) », « Vérifié (MCP réel) », « Vérifié (script) » et « Non exécuté », avec leur légende.

## Constats des relectures finales

Intégrés : chemin Python du lanceur fixé dans le script, limite GitHub du push, quatre identifiants cités par Haiku, preuve `repreneur-result.json`, libellés exacts des fenêtres, prérequis Claude Code et claude-tap, définition de DATA_DIR, CLE_SESSION et ID_PROJET, légende de la figure 8.

Reportés (non bloquants) :

- pas de section dédiée à l'installation de Claude Code, claude-tap et Git ; le guide renvoie à la reprise manuelle si ces outils manquent ;
- pas de glossaire (MCP, trace, Haiku, Sonnet, noms d'outils MCP) ;
- chemins en `E:\` et `E:/` mélangés ; les deux fonctionnent sous PowerShell ;
- étapes du §10 à l'impératif, sous l'avertissement « déjà fait dans Orion livré ».

## Limites

La seconde passe n'a pas été relue par un relecteur indépendant. Aucune commande du guide n'a été réexécutée dans cette session. Le lanceur ne fonctionne que sur ce poste. La Reprise Orion par un nouvel agent n'a pas été exécutée. Les tests métier des applications boutique, inscription et stock restent des recettes proposées.
