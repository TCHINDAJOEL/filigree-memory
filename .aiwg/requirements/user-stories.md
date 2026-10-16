# Filigree — histoires, critères et traçabilité

Date : 15 octobre 2026. Auteur et synthétiseur : agent produit/architecture. Statut : critères révisés après les revues domaine et interface, résultats à renseigner dans les rapports de vérification. Adaptation compacte du modèle AIWG `templates/requirements/user-story-card.md`. Les différences de périmètre sont explicitées dans [la synthèse](../testing/review-synthesis.md).

Besoin transversal : transmettre la compréhension corrigée d'un projet, aux humains comme aux agents. Valeur attendue : moins de réexplications et de décisions périmées ; aucune économie chiffrée revendiquée avant mesure. Risques : perte de provenance, confusion entre acceptation et preuve, changement des formats de capture, écritures concurrentes.

Chaque critère ci-dessous est une cible d'acceptation, pas une affirmation que le test a déjà réussi. L'orchestrateur relie les identifiants aux fichiers et résultats réels après intégration.

| ID / priorité | Histoire | Critères observables | Périmètre / preuve attendue |
| --- | --- | --- | --- |
| US-01 / critique | Porteur du projet, je conserve un projet identifié et son objectif, puis je regroupe ses connaissances par libellé d'épisode au-delà d'une session. | Créer un projet conserve son identifiant et sa description d'objectif après redémarrage ; des notes de sessions différentes partagent un libellé d'épisode et sont retrouvables par ce libellé. Aucun identifiant, objectif ou cycle de vie autonome d'épisode n'est promis en v0.1. | Stockage + interface ; aller-retour disque et recherche du libellé |
| US-02 / critique | Contributeur, je remonte d'une connaissance à sa source pour juger sa portée. | Une proposition issue d'un import affiche une source et un extrait ; une note manuelle est explicitement attribuée à sa saisie, sans inventer de trace. | Import + vue détail ; source consultable |
| US-03 / critique | Responsable, je gouverne les propositions pour que le courant reste fiable. | Accepter ou rejeter modifie le statut et conserve les anciennes révisions ; une raison de revue saisie explicitement est conservée et consultable. Sans raison saisie, le système n'en invente pas. Une importation ne s'auto-accepte pas. | Domaine + interface ; transitions, motif et contenu des anciennes révisions |
| US-04 / critique | Responsable, je recadre une décision sans effacer la discussion. | Une décision remplacée reste retrouvable et liée à sa remplaçante ; la reprise distingue les deux. Un remplacement invalide est refusé. | Relations + reprise ; scénario Basic Memory |
| US-05 / haute | Lecteur, je recherche et parcours les liens pour comprendre les raisons d'un choix. | Recherche par texte, filtres par statut ou type, sélection d'un nœud vers sa fiche ; graphe et liste désignent les mêmes identifiants. | Interface + recherche ; vérification navigateur |
| US-06 / critique | Nouvel arrivant, je reçois une fiche de reprise pour continuer dans le bon sens. | La fiche présente objectif, décisions applicables, pistes écartées, incertitudes et sources disponibles ; les propositions ne sont pas formulées comme acceptées. | Export Markdown ; assertions de contenu |
| US-07 / haute | Utilisateur de claude-tap, j'importe un fichier choisi pour éviter la recopie. | Import des familles JSONL et tableau JSON documentées ; réimport et historiques répétés dédupliqués selon l'identité documentée ; dates source disponibles conservées distinctement de l'import. Compact et WebSocket brut sont refusés explicitement. La surveillance CLI concerne uniquement un fichier choisi. | Adaptateur + CLI ; fixtures synthétiques représentatives et limites documentées |
| US-08 / haute | Agent, je lis la mémoire et propose une note avec les mêmes règles que l'humain. | Initialisation MCP, découverte des outils, recherche et proposition fonctionnent ; la proposition reste proposée ; aucun outil d'acceptation n'est exposé. | MCP stdio ; échange JSON-RPC |
| US-09 / haute | Propriétaire, je conserve ma mémoire hors de l'application. | Les connaissances sont lisibles sur disque et récupérables après redémarrage sans service tiers ; un checkpoint Git ne capture aucun fichier étranger au périmètre mémoire. | Stockage + Git ; inspection du commit |
| US-10 / critique | Propriétaire, je garde mes originaux externes et mes données inertes. | L'import n'archive pas automatiquement les originaux bruts ; le checkpoint n'ajoute pas ces fichiers externes. Les extraits font partie de la mémoire et peuvent être exportés : ce périmètre est expliqué. Une source contenant du HTML actif s'affiche comme texte ; l'API locale refuse les appels web d'une origine non autorisée. | HTTP + rendu + Git ; contrôles sécurité ciblés |

## Activation automatique par dossier (16 octobre 2026)

Complète les stories ci-dessus ; remplace leur restriction à l'import manuel pour le parcours principal. Exigence : [automatic-capture.md](automatic-capture.md). Décision : [ADR-0002](../architecture/ADR-0002-automatic-project-capture.md). Critères de sortie : [capture-acceptance.md](../testing/capture-acceptance.md). Ce sont des cibles ; les résultats exécutés vivent dans `.aiwg/testing/verification.md`.

| ID / priorité | Histoire | Critères observables | Preuve attendue |
| --- | --- | --- | --- |
| US-11 / critique | Utilisateur, une session Claude ou Codex dans un dossier réel crée ou alimente la mémoire de ce dossier sans création préalable. | L'identifiant de session d'un record claude-tap ou d'une transcription native égale **exactement** celui d'une transcription qui nomme un dossier existant ; le projet est le plus proche ancêtre enregistré, sinon la racine Git, sinon le dossier. Les sessions antérieures au démarrage ne sont pas importées. | Tests de liaison exacte et de ligne de base ; essai manuel `verify_live_capture.py` (un client, une machine) |
| US-12 / critique | Claude et Codex dans le même dossier alimentent un seul projet ; deux dossiers restent isolés. | Un projet par dossier, aucun contenu croisé, ordre temporel entrelacé. | Tests deux agents / deux dossiers, avec et sans claude-tap |
| US-13 / critique | Chaque observation garde sa provenance de collecte et reste une proposition. | Statut « À examiner » ; collecteur, session tap, index de record, empreinte de la charge, identifiant natif, dossier et mode de lien sont dans l'entrée. Un choix explicite est marqué comme tel et n'est pas présenté comme une preuve de dossier natif. | Fichiers d'entrée et vue détail |
| US-14 / critique | Une session sans rattachement exact reste en attente et se rattache explicitement. | Aucun contenu dans un projet arbitraire ; clés et motifs seulement, jamais de texte. Une transcription native non résolue est retenue à son décalage et relue dans l'ordre à la résolution. Un rattachement `tap:ID` ne vaut que pour la base claude-tap choisie. Une pause ou exclusion délibérée est la seule perte assumée. | Vue Capture, `capture pending/link/unlink`, tests de retenue et de portée par base |
| US-15 / haute | Pause, exclusion, reprise, redémarrage et plantage ne perdent pas l'état et ne dupliquent rien. | Curseurs, déduplication par URI et par registre inter-canaux, un seul moniteur par dossier de données. | Tests de curseur, crash, verrou |
| US-16 / haute | Le moniteur expose l'état réel des sources. | Capacités tap `ok`, `missing`, `locked`, `corrupt`, `unsupported_schema` ; moniteur actif ou arrêté ; compteurs ; aucune lecture hors schéma 4 ; pas de faux succès. | API `/api/capture`, vue Capture, tests d'intégrité |

Limites assumées : pas de capture sans moniteur actif ; clients non couverts (Claude Desktop conversation, Claude web) ; identifiants déclaratifs et non authentifiés ; masquage de secrets heuristique ; aucune synthèse sémantique ni pensée cachée.

## Scénarios métier de référence

**SC-01 — Recadrage.** Une note propose un socle ; une intervention précise que ce choix n'est pas décidé. L'humain conserve la proposition et accepte le recadrage. La reprise exprime la suspension du choix. Elle ne généralise pas cette instruction en préférence permanente.

**SC-02 — Tentative échouée.** Une tentative est associée à une observation de test négative. La raison de son abandon reste consultable. Le système ne transforme pas une commande réussie en démonstration que le besoin entier est satisfait.

**SC-03 — Passage Claude → humain → autre agent.** Importer une trace de démonstration, organiser les notes et statuts, exporter une reprise, puis lire cette même reprise via MCP. L'évaluation de la compréhension d'un vrai second modèle est distincte de la conformité du transport MCP ; aucune compatibilité client non essayée n'est revendiquée.

**SC-04 — Correction et portabilité.** Modifier la compréhension, conserver l'historique, déplacer une copie de la mémoire, rouvrir. Les identifiants de projet et connaissances ainsi que leurs liens restent cohérents ; les extraits embarqués restent lisibles. Les références externes sont du texte : la v0.1 ne vérifie pas automatiquement la présence des fichiers originaux ni ne les copie.

## Matrice de traçabilité

| Besoin de la vision | Stories | Décision | Validation de sortie |
| --- | --- | --- | --- |
| Histoire intellectuelle | US-01, 02, 04, 05 | ADR-0001 | SC-01, SC-02 et démo navigateur |
| Contrôle humain | US-03, 04, 08 | ADR-0001 | Transitions, proposition MCP |
| Reprise fidèle | US-06, 07, 08 | ADR-0001 | SC-03 et test Basic Memory |
| Localité et portabilité | US-09, 10 | ADR-0001 | SC-04, Git isolé, HTTP local |
| Activation automatique par dossier | US-11 à 16 | ADR-0002 | Tests de capture ; essai live manuel étiqueté séparément |

La table des tests exécutés, de leurs résultats et des limites doit vivre dans `.aiwg/testing/`. Les critères non vérifiés restent ouverts au moment du gate ; cette spécification ne les clôture pas.
