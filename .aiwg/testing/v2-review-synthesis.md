# Synthèse des revues — cadrage V2

Date : 17 octobre 2026. Synthétiseur : orchestrateur (Opus), auteur du brouillon. Les revues ont été faites par trois agents indépendants (Sonnet), qui n'avaient pas rédigé le document. Objet : [v2-vision-cadrage.md](../architecture/v2-vision-cadrage.md), passé de la révision 1 à la révision 2. Revues : [architecture](v2-review-architecture.md) (A-01…A-16), [sécurité](v2-review-securite.md) (S-01…S-18, R-01…R-04), [produit](v2-review-produit.md) (P-01…P-17).

Nature de la vérification : **revue documentaire uniquement**. Aucun code n'a été écrit ni exécuté, et aucune sonde n'a été lancée. Les observations locales [O] se limitent à des noms de champs et des comptages, sans contenu de conversation.

## Points bloquants

| Constat | Traitement dans la révision 2 | Statut |
| --- | --- | --- |
| A-01 Journal présenté comme reconstructible | Le journal devient une **donnée conservée**, non jetable ; la révision de l'ADR-0001 est annoncée pour l'ADR-0003 ; les propositions embarquent leur extrait (§7) | Corrigé dans le cadrage, ADR-0003 à écrire |
| A-02 Journal global ; texte des sessions en attente | Journal **par projet** ; sessions en attente stockées en clé seule, sans texte (§7) | Corrigé |
| A-03 / S-01 Hook non authentifié, chemin fourni | Hook = **signal de réveil seul**, charge utile `{client, session_id, event}` ; aucun chemin lu ; clé durable par installation ; preuve relue dans le store (§4, §8) | Corrigé |
| A-04 Common dir et clones | Worktree prouvé par lien **dans les deux sens**, lecture de fichiers, repo déjà enregistré ; clones et sous-modules jamais fusionnés (§6 règle 2) | Corrigé |
| S-02 Injection de l'activité non revue | Reprise limitée aux connaissances **acceptées** ; D4 réécrite (§3, §12) | Corrigé |
| S-03 Consentement par exclusion | **Opt-in** par racines autorisées ; rien lu avant l'accord ; hors racine = clé seule (principe 2, §8) | Corrigé |
| S-04 Distillation distante | Modèle distant **exclu de la V2** ; option D3 = modèle local seulement | Corrigé |
| S-05 Installation en une ligne non vérifiable | Version épinglée, script publié par release, empreinte SHA-256, tag signé, voie « lire puis exécuter » documentée (§8) | Corrigé dans le cadrage, à réaliser en V2.0a |

## Points majeurs

| Constat | Traitement |
| --- | --- |
| A-05 Clé de session, reprise et fork | Clé = client + racine source + id ; déduplication par identifiant d'élément source (§6 règle 4) |
| A-06 Changement de `cwd` | Rattachement au projet du premier `cwd` ; événements `outside_project` ; `ambiguous_cwd` de la v0.1 conservé (§6 règle 1) |
| A-07 Incohérence D4 et §10 | Résolu avec S-02 |
| A-08 `auto_create` | Uniquement dans une racine autorisée (D13) |
| A-09 Rôles des processus | `filigree agent` = seul processus de capture ; `serve` = alias ; MCP sans capture (§8) |
| A-10 Reprise entre deux stores | Protocole : écriture idempotente, puis curseur, puis distillation par clé (§7) |
| A-11 Budget non mesuré, verrou | Budget chiffré en critère de sortie ; écritures Markdown par lots courts ; surveillance plafonnée (§4, §7, §8) |
| A-12 Processus | Rôle **décoratif** seulement, PID avec heure de démarrage (§4, §6 règle 5) |
| S-06 API permanente | Jeton exigé pour toute requête, lectures comprises (§8). *Le comportement actuel des lectures v0.1 n'a pas été vérifié par la revue sécurité.* |
| S-07 Secrets | Expurgation avant stockage ; aucune source brute resservie ; `detail_ref` supprimé (§7) |
| S-08 Purges des agents | Aucun rattrapage automatique ; proposé par projet ; sessions archivées exclues (§5, D11) |
| S-09 Configuration des hooks | Diff, sauvegarde horodatée, portée utilisateur seule, journal d'installation (§8) |
| S-10 Invariant de modification silencieuse | Tableau des invariants (§9) ; amendement d'`AGENTS.md` **par l'humain** (D1) |
| S-11 Preuves forgeables | Limite documentée (§6) ; atténuée par l'injection limitée à l'accepté |
| S-12 Fuite MCP entre projets | Portée MCP = projet du client (§8) |
| S-13 CGU | Frontière : métadonnées d'identité seulement, aucun contenu de cache de chat (§5). **Conformité juridique non établie : à faire confirmer.** |
| S-14 Stockage au repos | Permissions restrictives, refus des dossiers synchronisés sans confirmation, absence de chiffrement documentée (§7, §10) |
| P-01 Limites mal placées | Encadré « Ce que V2 ne fera pas » en tête |
| P-02 Zéro geste contre assistant | Un seul accord obligatoire ; reste en mode avancé (§8) |
| P-03 Gain visible en V2.0 | Vue « Sessions du jour » en V2.0b |
| P-04 V2.0 trop lourde | Windows d'abord ; découpage V2.0a / V2.0b ; tailles et dépendances (§11) |
| P-05 Critères non chiffrés | Critères mesurables par lot (§11) |
| P-06 Promesse sur les décisions | Dit explicitement : activités en V2.0-2.2, décisions humaines (§3, En bref) |
| P-07 Couverture surévaluée | « Sous réserve de sonde » + D9 (§5) |
| P-11 Décisions manquantes | D9 à D14 ajoutées |
| P-15 Clarté | Résumé, glossaire, tableau §5 réduit à 6 colonnes |

## Points mineurs

A-13 (normalisation des chemins) : `canonical_folder` de la v0.1 réutilisé (§9). WSL et MSIX restent à sonder. A-14 : `ts_observed` et règle d'horodatage futur (§6). A-15 : propositions indépendantes du journal (§7). A-16 : version de schéma et migrations (§7). S-15 : lignes de commande jamais stockées. S-16 : en-têtes tap jamais lus. S-17 : plafond de propositions, pas d'acceptation en lot. S-18 : `filigree status` liste les artefacts, `uninstall` testé. P-08, P-09 : indicateur permanent et « lu aujourd'hui ». P-10 : seuil des chevauchements. P-12 : D1 mentionne l'amendement d'`AGENTS.md`. P-13 : D8 reformulée. P-14 : marquage « sous réserve ». P-16 : règle sur [C] et [?]. P-17 : tailles S/M/L.

## Reporté (assumé)

R-01 multi-utilisateur, R-02 programme malveillant sous le même compte, R-03 chiffrement au repos et exécutable signé, R-04 OTLP, MITM et scraping (exclus). macOS et Linux sont prévus en V2.x.

## Reste ouvert avant implémentation

1. Décisions utilisateur D1 à D14.
2. ADR-0003 (journal par projet, révision des invariants, collecteurs, démon), à rédiger puis à faire relire indépendamment.
3. Sondes D9 sur des installations réelles : rien n'est encore exécuté.
4. Vérification de l'authentification des lectures de l'API v0.1 (S-06).
5. Avis sur les CGU (S-13), hors compétence de l'équipe.
