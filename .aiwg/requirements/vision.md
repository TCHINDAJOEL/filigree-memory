# Filigree — conserver le pourquoi du projet

Date : 15 octobre 2026. Auteur et synthétiseur : agent produit/architecture. Statut : cadrage révisé après deux revues indépendantes ; acceptation de livraison soumise aux tests et au gate. Voir [la synthèse](../testing/review-synthesis.md).

Adapté du modèle AIWG `templates/requirements/vision-informal-template.md`, retrouvé dans l'installation `.claude/plugins/marketplaces/aiwg/agentic/code/frameworks/sdlc-complete/` ; le chemin `.Codex` communiqué est absent. Source métier : document fourni par l'utilisateur et autorisation de réalisation. Les choix ci-dessous sont des décisions de réalisation déléguées, pas des réponses inventées à un entretien utilisateur.

## 1. Introduction

Filigree est une application locale de documentation vivante. Elle permet à une personne ou un agent de comprendre ce qui est décidé, pourquoi, ce qui a été essayé, ce qui a changé et ce qui reste incertain. Le projet possède une identité stable et une description de son objectif. En v0.1, l'**épisode** est un libellé commun aux connaissances pour regrouper un problème traversant plusieurs sessions ; il n'a pas d'identifiant ni d'objectif propre. Une entité épisode autonome appartient à la suite du produit.

## 2. Positionnement

Les fichiers montrent le résultat du travail ; les conversations dispersent son cheminement. Le prochain contributeur doit souvent redécouvrir les raisons des choix. Filigree relie des connaissances lisibles à leurs sources et à leurs évolutions, puis produit une fiche de reprise.

Le bénéfice à démontrer est une reprise fidèle. L'adoption massive et le gain de temps ne sont pas encore mesurés. Le produit ne récupère pas les pensées internes cachées des modèles et ne présente pas une suggestion comme une décision humaine.

## 3. Utilisateurs et environnement

| Utilisateur | Travail attendu | Contrôle |
| --- | --- | --- |
| Porteur du projet | Organiser, corriger et valider la mémoire | Statuts, raisons, sources et liens explicites |
| Nouveau contributeur humain | Comprendre l'histoire sans relire toutes les conversations | Consultation des alternatives, des preuves et des limites |
| Agent IA | Reprendre le contexte et proposer des connaissances | Lecture et proposition ; pas d'acceptation automatique via MCP |

Hypothèse de départ : une personne pilote un projet local à la fois ; navigateur de bureau, Python 3.11 ou supérieur, Git facultatif pour les checkpoints. Le logiciel peut être public, les mémoires et traces des utilisateurs restent distinctes. Aucune connexion à un fournisseur de modèle n'est nécessaire pour ouvrir et gouverner la mémoire.

## 4. Vue du produit

Parcours : créer ou ouvrir le projet et préciser son objectif → regrouper les notes par libellé d'épisode → importer une trace ou écrire une note → examiner les propositions → accepter, rejeter ou remplacer → explorer les liens et révisions → transmettre la fiche de reprise.

**Mise à jour du 16 octobre 2026 (activation automatique, [exigence](automatic-capture.md)).** Le parcours principal est l'activation par dossier : un moniteur local lit en lecture seule la base claude-tap (schéma 4) et, pour un client lancé directement, les transcriptions locales de Claude Code ou de Codex ; une session dans un dossier réel identifié par un identifiant de session **exactement égal** alimente le projet de ce dossier, créé à la première utilisation. Tout arrive en propositions avec provenance. L'import explicite et la surveillance CLI d'un fichier choisi restent des parcours de récupération. Filigree ne lance pas les agents, n'intercepte aucune application, ne modifie aucune configuration d'agent, n'appelle aucun modèle et ne fait pas d'extraction sémantique ; le raisonnement caché n'est pas collecté. La couverture est celle des sources locales réellement lisibles (voir l'[ADR-0002](../architecture/ADR-0002-automatic-project-capture.md) et le README) ; Claude Desktop (conversation) et Claude sur le web ne sont pas couverts. Le script Claude utilisé pendant le développement est un outil de réalisation du dépôt, pas un lanceur intégré au produit.

| Besoin | Priorité | Première version |
| --- | --- | --- |
| Comprendre l'intention actuelle | Critique | Objectif du projet, libellés d'épisode et fiche de reprise sourcée |
| Conserver les recadrages | Critique | Connaissance de type recadrage ; liens vers les éléments concernés |
| Gouverner les conclusions | Critique | Proposition, acceptation, rejet, remplacement ; journal des changements |
| Retrouver l'origine | Critique | Source et extrait, avec identifiant stable |
| Capturer une session | Critique | Capture automatique par dossier (claude-tap + transcriptions natives), propositions avec provenance ; import explicite et surveillance d'un fichier choisi en récupération |
| Explorer le pourquoi | Haute | Recherche, filtres et graphe de relations explicites |
| Transmettre à un autre outil | Haute | Markdown et interface MCP locale |
| Garder la maîtrise des fichiers | Haute | Mémoire lisible ; checkpoints Git limités à son périmètre |
| Apprendre des méthodes personnelles | Ultérieure | Propositions de procédures, après plusieurs expériences et validation |

Alternatives fonctionnelles : un dossier de Markdown et des ADR suffit pour une petite histoire tenue manuellement ; un visualiseur de traces explique les échanges mais ne gouverne pas leur statut ; une mémoire sémantique automatique aide à rappeler des éléments mais demande une évaluation propre de leur fidélité. La première version privilégie l'explicitation des connaissances, sans prétendre avoir comparé expérimentalement tous les produits concurrents cités dans l'échange initial.

## 5. Qualité attendue

- Une démonstration utilisable sans clé API ni serveur distant, avec des données fictives identifiées.
- Une reprise qui distingue accepté, proposé, rejeté et remplacé ; une affirmation sans preuve reste sans preuve.
- Une provenance visible et un historique lisible après correction.
- Des erreurs explicites pour un format non pris en charge ; pas de succès silencieux avec zéro contenu utile.
- Des traces importées traitées comme données non fiables ; leur texte n'exécute ni HTML, ni commandes.
- Les originaux bruts restent dans leur emplacement externe local : Filigree ne crée pas automatiquement une archive brute privée. Les extraits de source sont conservés dans la mémoire canonique ; un export ou checkpoint peut donc les inclure. Ils peuvent contenir des données sensibles malgré l'expurgation heuristique.

## Cas d'acceptation déterminant

Une ancienne réponse propose Basic Memory. L'utilisateur recadre : définir la méthode avant de choisir le socle. Après gouvernance, la fiche de reprise indique que le socle reste à choisir et conserve la proposition antérieure avec son statut. Elle ne dit ni « Basic Memory est choisi », ni « l'utilisateur refuse toujours les recommandations d'outils ».

Voir [les histoires et critères](user-stories.md), [la décision d'architecture](../architecture/ADR-0001-local-portable-memory.md) et [le plan de livraison](../planning/delivery-plan.md).
