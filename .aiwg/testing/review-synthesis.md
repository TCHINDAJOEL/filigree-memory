# Synthèse auteur → reviewers → synthétiseur

Date : 15 octobre 2026. Synthétiseur : agent produit/architecture. Périmètre : vision, stories, ADR, note d'intégration et plan de livraison, confrontés aux trois revues et à une lecture ciblée des corrections. **Aucun test exécuté par le synthétiseur. Aucun gate de livraison clos ici.**

## Circuit de revue

| Étape | Responsable | Artefacts / preuve |
| --- | --- | --- |
| Auteur | Agent produit/architecture | `requirements/vision.md`, `requirements/user-stories.md`, `architecture/ADR-0001-local-portable-memory.md`, `architecture/claude-tap-integration.md`, `planning/delivery-plan.md` |
| Reviewer indépendant 1 | Agent domaine | [review-domain.md](review-domain.md) : revue des artefacts qu'il n'a pas écrits ; ne vaut pas revue indépendante de son propre store |
| Reviewer indépendant 2 | Agent interface | [review-interface.md](review-interface.md) : revue des artefacts qu'il n'a pas écrits |
| Revue croisée d'implémentation | Agent produit/architecture | [review-product.md](review-product.md) : lecture de store/importers/git_sync/claude_runner, dont il n'est pas l'auteur |
| Synthétiseur | Agent produit/architecture | Présent document et corrections cohérentes des cinq artefacts |
| Intégration / gate | Chef d'orchestre | Tests exécutés, preuves navigateur, décision de sortie et publication à consigner séparément |

Les rapports de revue initiaux restent conservés sans être réécrits pour effacer les défauts découverts. La présente synthèse décrit leur traitement à cet instant. « Implémenté en lecture » signifie qu'un changement existe dans le code inspecté, pas qu'un test a réussi.

## Décisions produit explicites

**Épisodes.** RD-05 et la remarque interface 1 sont retenus. US-01 porte désormais sur un projet avec identifiant stable et description d'objectif, puis un **libellé d'épisode** commun aux connaissances de plusieurs sessions. Il n'existe pas en v0.1 d'entité épisode avec identifiant, objectif ou état propre. Cette capacité est placée dans la roadmap ; l'ancien critère n'est pas déclaré satisfait sans réalisation.

**Sources.** RD-09 est retenu. Le diagramme ne montre plus une archive brute privée inexistante. Les originaux restent externes ; l'application n'en conserve pas automatiquement une copie. Les extraits de provenance appartiennent à la mémoire canonique et peuvent être inclus dans un checkpoint ou export. La résolution automatique des références de fichiers absents n'est plus promise par SC-04.

**Capture et agents.** L'application importe explicitement ou surveille un fichier JSON/JSONL choisi via CLI. Elle ne capture pas toutes les conversations du poste, ne lance pas Claude/Codex et ne produit pas de synthèse LLM automatique. MCP offre lecture et proposition. Le script `scripts/claude_runner.py` est un auxiliaire du développement du dépôt, pas un parcours utilisateur intégré.

**Gouvernance.** Une raison explicitement saisie doit être conservée ; une raison absente ne sera pas inventée. « Acceptée » reste une validation humaine locale, pas une preuve indépendante ni une signature authentifiée. Le contexte de reprise distingue courant, incertitudes et historique non applicable.

## Résolution des findings

| Référence | Résolution observée / décidée | Statut au moment de la synthèse | Preuve restant à obtenir |
| --- | --- | --- | --- |
| RD-01 / produit duplication | L'empreinte n'utilise plus le numéro d'enregistrement ni le timestamp ; identité de contenu, agent, épisode et extraits/références. | Implémenté en lecture, validation en attente | Historiques répétés et réimport ; documenter la fusion de messages réellement identiques et l'absence d'agrégation de toutes leurs occurrences |
| RD-02 / WebSocket | L'adaptateur refuse explicitement les événements WebSocket bruts avant persistance. | Implémenté en lecture, validation en attente | Fixture refusée, aucune écriture partielle ; export normalisé utilisable |
| RD-03 / enveloppes | Contrôles ajoutés avant accès à `request` et `payload`. | Implémenté en lecture, validation en attente | Objets/listes/chaînes/null malformés ; message utilisateur cohérent |
| RD-04 / limite d'import | Adaptateur ramené à 1 000 enregistrements/événements ; store limité à 1 000. | Implémenté en lecture, validation en attente | Expansion au-delà de la limite rejetée intégralement |
| RD-05 / interface 1 / épisode | US-01, vision, ADR et roadmap alignés sur libellé d'épisode ; entité autonome différée. | ✓ Décision de périmètre documentée | Redémarrage, regroupement et recherche réels du libellé |
| RD-06 / interface 4 / produit reprise | `handoff` inclut objectif et trois groupes : courant, incertitudes, historique `NOT CURRENT`, sous budget. | Implémenté en lecture, validation en attente | Ancienne alternative et sa raison visibles sans devenir applicables ; budget et omissions |
| RD-07 / interface 2 / produit motif | Le store accepte `reason`, l'expurge et le conserve dans l'événement de mise à jour. | Domaine implémenté en lecture ; intégration interface à confirmer | Saisie du motif, transition, lecture ultérieure et contrôle d'une raison absente |
| Interface 3 / historique | `Store.list_history` et route HTTP de lecture ajoutées. | Domaine/route implémentés en lecture ; navigateur à confirmer | Afficher une ancienne révision, distinguer contenu courant et historique |
| RD-08 / produit date | Timestamp disponible conservé dans la provenance, séparé des dates de création/import. | Implémenté en lecture, validation en attente | Import hors ordre ; date manquante ; ne pas confondre date de requête et date originale de tous ses messages |
| RD-09 / sources | Diagramme, vision, US-10 et SC-04 corrigés : extraits canoniques, originaux externes, pas de résolution automatique. | ✓ Contrat corrigé | Inspection des fichiers et de l'export réel |
| Produit P1 Git / RD-10 | Refus des fichiers préindexés hors `project.json`, `.gitignore`, `.filigree/` ; pathspecs conditionnels et `.tmp-*` ignorés. | Correction partielle en lecture ; contrôle d'intégration requis | Checkpoint vide, index préexistant préservé et isolation ; `.filigree/` reste ajouté en bloc, donc tout fichier manuel sous ce dossier doit être traité explicitement |
| Produit P2 runner quota | Le résultat JSON est analysé d'abord ; une exécution réussie ne peut plus être classée quota sur une simple citation. | Implémenté en lecture, validation en attente | Succès citant `rate_limit_error` et vraie erreur de quota |
| Validation après expurgation | `_new` et `update_entry` valident les données après redaction. | Implémenté en lecture, validation en attente | Entrées dont l'expurgation modifie la longueur ou les champs obligatoires |

## Limites assumées et réserves

La déduplication actuelle représente une mémoire de contenus, pas un journal exhaustif de chaque occurrence : des messages strictement identiques avec le même contexte d'identité peuvent être fusionnés. Leur multiplicité et toutes les dates d'apparition ne sont pas garanties. Cette limite doit rester visible dans la documentation publique ; elle ne doit pas être formulée comme une capture parfaite de la conversation.

Les anciennes alternatives sont abrégées dans la reprise et les blocs hors budget sont comptés. Les notes canoniques restent le moyen de consulter le texte entier. Les raisons d'un rejet peuvent être conservées dans le journal de revue ; vérifier leur présence dans le parcours de reprise attendu, sans supposer que le corps contient toujours cette raison.

L'isolation Git doit être jugée sur le commit réel et les fichiers autorisés, pas seulement sur le répertoire courant ou le `.gitignore`. L'ajout global de `.filigree/` reste une réserve si l'utilisateur y a placé un original brut ou un fichier privé. La publication du logiciel n'autorise pas implicitement celle de toutes les mémoires des utilisateurs.

## Sortie de synthèse

✓ Deux revues indépendantes des artefacts ont été prises en compte ; les écarts de produit sont explicités et les documents archivés dans `.aiwg/`.

⏳ Restent les scénarios exécutés par le testeur, la vérification visuelle, les contrôles HTTP/MCP/Git et la décision de gate par l'orchestrateur. Aucun pourcentage de réussite, gain utilisateur ni compatibilité client non essayée n'est déduit de cette synthèse.
