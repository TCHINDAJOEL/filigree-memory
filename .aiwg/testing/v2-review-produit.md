# Revue produit et faisabilité — cadrage Filigree V2

Date : 2026-10-17. Rôle : relecteur indépendant produit et faisabilité (n'a pas rédigé le document). Périmètre : `.aiwg/architecture/v2-vision-cadrage.md`, relu avec `requirements/vision.md` et `user-stories.md`. Le brouillon n'a pas été modifié. Aucun test exécuté : revue documentaire uniquement.

## Verdict

Cadrage solide, honnête sur les sources de preuve et cohérent avec les invariants de la v0.1. Quatre points à corriger avant validation : la couverture des 8 demandes est incomplète sur deux points (« une ligne » et « UX entièrement automatisée »), l'avertissement sur ChatGPT/Claude chat est correct mais enfoui, la V2.0 promet plus qu'elle ne montre à l'utilisateur, et plusieurs critères restent non mesurables.

## 1. Couverture des 8 demandes

| Demande | Traitée ? | Où | Commentaire |
| --- | --- | --- | --- |
| 1. Install une ligne (comme claude-tap) | Oui, partiel | F1, §8 | La ligne `irm \| iex` est citée, mais `filigree setup` est interactif : ce n'est plus « une ligne et c'est fini ». Voir P-02. |
| 2. Détection auto des 5 outils | Partiel | §4, §5 | Les 5 sont couverts dans la matrice, mais ChatGPT et Claude chat sont « export seulement ». |
| 3. Service permanent discret | Oui | F2, §8 | Tâche planifiée, LaunchAgent, systemd. « Discret » n'a pas de critère (icône reportée en V2.x). |
| 4. Identification auto du projet | Oui | F5, §6 | Bien traité (git common dir). Cas « dossier sans git ni projet enregistré » seulement implicite. |
| 5. Plusieurs terminaux/agents corrélés mais distincts | Oui | F6, F9, §6 | Mais livré en V2.1, pas en V2.0. |
| 6. Traces nettoyées, structurées, activités/décisions/changements | Partiel | F7, F8, §7 | Activités et changements : oui (déterministe). **Décisions : seulement « candidates », via modèle optionnel (D3, désactivé par défaut).** |
| 7. UX entièrement automatisée | Partiel | Principe 1, F9, F10 | L'UX décrite reste centrée sur des vues à consulter et des propositions à accepter. Aucune section « parcours utilisateur ». |
| 8. Fonctions complémentaires | Oui | §3 | Liste utile, ★ bien choisies. |
| Évoluer la V1 sans reconstruire | Oui | §9 | Tableau garder/étendre/refondre clair. `capture.py` « refondre » mérite d'être nuancé. |

## 2. Constats

| ID | Gravité | Section | Constat | Recommandation |
| --- | --- | --- | --- | --- |
| P-01 | majeur | §1, §5, §12 | Le fait que ChatGPT et Claude chat ne seront PAS capturés automatiquement n'apparaît qu'à la fin du §5 (l. 116) et en D6. La vision (§1) parle d'« une application de bureau » sans réserve. L'utilisateur lira « détection automatique des 5 outils » et sera déçu. | Ajouter en tête du document (sous la vision) un encadré « Ce que V2 ne fera pas » avec un tableau 5 outils : automatique / partiel / non. Reformuler la vision en nommant les outils couverts. |
| P-02 | majeur | §8 (setup), F1 | « Zéro geste » et « assistant interactif en 5 étapes avec consentement » se contredisent en apparence. Une ligne d'install suivie de questions n'est pas ce que décrit la demande. | Définir un mode par défaut « recommandé » en un seul accord (une question), et réserver le détail aux options avancées. Écrire le nombre de clics maximal visé. |
| P-03 | majeur | §11 V2.0 | V2.0 prétend livrer « zéro geste » mais sa preuve est « sessions capturées » : l'utilisateur ne voit pas de valeur nouvelle, la v0.1 capturait déjà les transcriptions Claude Code/Codex. Le gain visible (vue multi-sessions, fiche de session) arrive en V2.1. F6/F9 (distinction des terminaux) manquent en V2.0. | Inclure en V2.0 une vue projet minimale « sessions du jour » (liste par agent/terminal) et la page Couverture, afin qu'une démo montre : installer, redémarrer, ouvrir, voir ses sessions classées. Sinon renommer V2.0 « Fondations ». |
| P-04 | majeur | §11 V2.0 | V2.0 est lourde : installeur 3 OS, service 3 OS, registre de collecteurs, refonte de `capture.py` (1 493 l.), 2 nouveaux collecteurs, consentement. Risque de dérive. Les 3 OS ne sont pas priorisés alors que le poste réel est Windows. | Windows d'abord (V2.0), macOS/Linux en V2.0b. Séparer en V2.0a (service + installation) et V2.0b (collecteurs). Annoncer l'ordre de dépendance. |
| P-05 | majeur | §11 critères de sortie | Les critères de sortie sont des scénarios, pas des mesures : « sans aucun geste », « aucune fuite entre projets », « chronologie correcte » sans seuil. | Chiffrer : installation en moins de N minutes et au plus K saisies ; 0 mauvais rattachement sur un jeu de X sessions synthétiques ; latence de détection < 5 s p95 ; CPU repos < 1 %, RAM < 100 Mo mesurés (déjà cités §8, à reprendre dans les critères) ; taux de sessions en attente < Y %. |
| P-06 | majeur | §3, §7, D3 | Le besoin « décisions » est le cœur de la valeur, or le déterministe ne peut pas extraire une décision (seulement fichiers, commandes, tests). Les « décisions candidates » dépendent d'un modèle repoussé en V2.x. Le texte laisse croire le contraire (F8 « décisions candidates » §1). | Dire clairement : V2.0-2.2 produisent des activités et changements ; les décisions restent saisies/acceptées par l'humain ou proposées via la reprise MCP par l'agent lui-même. Proposer un levier sans modèle externe : l'agent propose la décision via MCP en fin de session (déjà dans la v0.1). |
| P-07 | majeur | §4, §5 | Ambiguïté sur « Codex App » et « Claude App » : la matrice indique « Complète » pour l'onglet Code, mais plusieurs preuves sont [C] ou [?] (synchro imparfaite, MSIX, hooks partagés [?]). L'affirmation « Complète » dépasse la preuve. | Remplacer « Complète » par « Complète sous réserve de sonde » pour ces lignes et lister les sondes à exécuter avant la promesse (voir D9). |
| P-08 | mineur | §10 | Le risque « l'utilisateur ne fait pas confiance à un service qui lit tout » est traité côté technique (pause, purge), pas côté perception. Aucun « mode visible » (indicateur de capture en cours). | Ajouter un indicateur d'état toujours accessible et un journal « ce que Filigree a lu aujourd'hui ». |
| P-09 | mineur | §3 | « Discret » (demande 3) : l'icône de notification est reportée en V2.x, donc l'utilisateur n'a aucun moyen de savoir si le service tourne sans ouvrir le navigateur. | Prévoir au moins une commande `filigree status` et une page Couverture ouverte au démarrage la première fois. |
| P-10 | mineur | §3 | Plusieurs fonctions ★ (reprise injectée, chevauchements) sont rattachées à la V2.2 ou V2.1 sans critère. Détection de chevauchement : faux positifs probables (fichiers de config, lockfiles). | Définir le seuil (même fichier source, hors liste d'ignorés) et un test. |
| P-11 | majeur | §12 | Décisions manquantes : (D9) Quelles sondes prouvent chaque ligne de la matrice avant de promettre ? (D10) Rétention du journal SQLite et purge (quelle durée par défaut ?). (D11) Que se passe-t-il pour l'historique antérieur à l'installation : rattrapage automatique ou demandé ? (D12) Plateformes prioritaires. (D13) Nom de commande et distribution : PyPI public ou local ? (D14) Politique de mise à jour automatique des parseurs quand un agent change de format. | Ajouter D9 à D14 avec recommandation. |
| P-12 | mineur | §12 D1, D4 | D1 et D4 se recouvrent avec la réalité d'un invariant (« pas de modification de configuration d'agent » dans `AGENTS.md`). Le fait que `AGENTS.md` doive être amendé n'est pas dit. | Mentionner que D1 impose de modifier l'invariant d'`AGENTS.md` et d'écrire l'ADR-0003 avant tout code. |
| P-13 | mineur | §12 D8 | D8 (rétrograder claude-tap) contredit l'ADR-0002 révision 2 et la mention de la demande utilisateur « comme claude-tap ». La demande visait l'expérience d'installation, pas la dépendance. Le texte ne le précise pas. | Reformuler : « on copie la simplicité d'installation de claude-tap, pas sa dépendance » et lier D8 à l'ADR. |
| P-14 | mineur | §5 | Plusieurs points [?] (statut `isSidechain`, hooks partagés Desktop) restent dans une table de « couverture V2 » comme s'ils étaient acquis. | Ajouter une colonne « confiance » ou marquer les cellules concernées. |
| P-15 | majeur | Clarté, tout le document | Public non expert français : forte densité de jargon non défini (collecteur, MITM, PEB, MSIX, OTel, OTLP, WAL, loopback, worktree, git common dir, MCP, `cwd`, hook). 290 lignes, tableaux très larges (7 colonnes en §5, illisibles). Le lecteur doit déjà connaître le sujet. | Ajouter (1) un résumé de 10 lignes en tête (quoi, pour qui, ce qui marche, ce qui ne marche pas, ce que vous devez décider) ; (2) un glossaire de 12 termes ; (3) déplacer §5, §10 et l'annexe vers un document technique ; (4) scinder le tableau §5 en une version simple (outil, capturé ?, comment) et une version détaillée. |
| P-16 | mineur | §1 | Légende [D]/[O]/[C]/[?] utile mais le lecteur non expert ne sait pas ce que « [C] » implique pour la promesse. | Une phrase : « [C] et [?] ne doivent jamais fonder une promesse commerciale ». |
| P-17 | mineur | §11 | Aucune estimation d'effort ni d'ordre de grandeur de durée par lot ; impossible de juger le réalisme. | Ajouter une taille relative (S/M/L) par lot et les dépendances. |

## 3. Réponses aux six questions

1. **8 demandes** : 5 pleinement traitées, 3 partiellement (installation une ligne, décisions, UX automatisée). Voir P-02, P-06.
2. **Honnêteté** : l'honnêteté est réelle, mais placée trop bas. Priorité P-01.
3. **Phasage** : ordre des lots cohérent (fondations, compréhension, accélération, chat). V2.0 n'apporte pas de gain visible nouveau (P-03) et est trop chargée (P-04).
4. **Critères** : non mesurables en l'état (P-05). Les budgets de §8 sont un bon point de départ.
5. **Décisions** : D1 à D8 sont pertinentes ; il manque D9 à D14 (P-11).
6. **Clarté** : insuffisante pour un non-expert (P-15).

## 4. Priorités avant validation utilisateur

1. P-01, P-15 : encadré « ce que V2 fait et ne fait pas » et résumé en tête.
2. P-03, P-05 : redéfinir V2.0 avec une valeur visible et des critères chiffrés.
3. P-06 : dire honnêtement que les décisions ne sortent pas du déterministe.
4. P-11 : compléter les décisions ouvertes.
