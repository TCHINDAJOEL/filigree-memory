# Revue indépendante — gouvernance, provenance et données

Date : 15 octobre 2026. Reviewer : agent produit/architecture, qui n'a écrit aucun des quatre modules examinés. Méthode : lecture statique de `filigree/store.py`, `filigree/importers.py`, `filigree/git_sync.py` et `scripts/claude_runner.py`. **Aucun test exécuté.** Les scénarios ci-dessous sont des reproductions proposées, pas des résultats d'exécution. Les numéros de ligne désignent l'état lu et peuvent se déplacer après correction.

Verdict initial : ⚠️ corrections nécessaires avant d'affirmer que le périmètre mémoire est isolé, que les historiques répétés sont dédupliqués et que la reprise conserve les pistes écartées. Les validations de schéma, statuts, références, révisions optimistes, verrou interprocessus et journal de récupération sont des fondations pertinentes.

## Findings prioritaires

### P1 — Le checkpoint capture des fichiers déjà indexés hors mémoire

**Localisation :** `filigree/git_sync.py:41-44`.

`git add` limite les nouveaux ajouts, mais `git commit -m` committe tout l'index existant. Un utilisateur qui a indexé un fichier privé dans ce dépôt mémoire avant le checkpoint verra ce fichier inclus ; le push ultérieur le publiera. Le contrat US-09/US-10 promet explicitement de ne capturer aucun fichier étranger. De plus, ajouter tout `.filigree` englobe n'importe quel fichier additionnel déposé sous ce dossier.

**Correction :** refuser les entrées indexées hors liste autorisée et les fichiers inconnus sensibles, ou créer le checkpoint avec un index temporaire contrôlé et une liste précise des fichiers de mémoire. Ne pas nettoyer l'index de l'utilisateur. Vérifier : un fichier étranger préindexé reste hors du commit et conserve son état initial.

### P1 — La reprise efface les alternatives rejetées et l'objectif du projet

**Localisation :** `filigree/store.py:467-491`, particulièrement `active` et le texte d'en-tête aux lignes 473-475.

Le handoff exclut tous les éléments `rejected` et `superseded` et ne conserve qu'un compteur ; il n'inclut pas non plus `project.description`. Dans un projet avec une tentative rejetée dont le corps explique l'échec, le prochain agent ne reçoit aucune explication de la piste écartée. Une relation vers un UUID exclu ne transmet pas cette raison. Cela contredit US-06 et le scénario de continuité central.

**Correction :** une section clairement étiquetée « historique non applicable » doit résumer les alternatives et leurs raisons, avec références, sans les réactiver ; inclure l'objectif disponible. Garder une limite de budget et expliquer séparément ce qui est omis faute de place. Vérifier qu'une note rejetée reste présentée comme rejetée et que sa raison est récupérable dans la reprise.

### P2 — Les mêmes messages présents dans plusieurs requêtes ne sont pas dédupliqués

**Localisation :** `filigree/importers.py:45-56,60,70-75` et `filigree/store.py:508-514`.

L'adaptateur réémet chaque message de l'historique complet pour chaque requête. L'événement inclut le timestamp de la requête et une source `enregistrement N`. Le store calcule son empreinte sur l'objet entier. Le même message présent aux requêtes 1 puis 2 a donc deux empreintes. Le réimport du même fichier est idempotent, mais un transcript croissant accumule des doublons et peut atteindre les limites d'import.

**Correction :** séparer l'identité stable d'un message de ses occurrences de provenance ; au minimum dédupliquer les historiques répétés dans une même session en conservant leurs références. Ne pas fusionner arbitrairement deux vrais messages distincts sans tenir compte du rôle, de la session et de l'identité du message. Vérifier avec deux requêtes dont la seconde contient l'historique de la première.

### P2 — La date de la source disparaît à la persistance

**Localisation :** `filigree/importers.py:52`, `filigree/store.py:510,523-528`.

L'adaptateur émet `timestamp`, mais le store n'enregistre que le texte, l'agent, l'épisode et les sources ; la date ne subsiste que dans l'entrée de calcul du hash, qui n'est pas réversible. Les dates `created_at` et `updated_at` sont les dates d'import. Deux sessions importées dans l'ordre inverse apparaissent donc sans moyen structuré de retrouver leur chronologie d'origine, alors que le produit conserve l'évolution de la compréhension.

**Correction :** conserver une date source distincte de la date d'enregistrement, avec son sens et sa disponibilité ; ne pas inventer une date absente. Pour les traces brutes, la date de requête n'est pas nécessairement la date de création de chacun des messages de son historique. Vérifier les imports hors ordre et une source dépourvue d'horodatage.

### P2 — Une décision peut changer de statut sans conserver la raison de ce changement

**Localisation :** `filigree/store.py:24,370-374,423-451`.

`EDITABLE` ne contient aucun champ de raison et `_save_entries` écrit un événement générique avec action et révisions. Accepter ou rejeter conserve la différence de statut mais pas pourquoi l'humain l'a fait. Modifier le corps pour y ajouter manuellement une raison est possible, mais ce n'est pas le comportement explicite promis par US-03 et ne distingue pas le contenu de la justification de transition.

**Correction :** rendre la justification de gouvernance enregistrable et visible dans l'événement/révision, ou réduire honnêtement le contrat de livraison si cette fonction est différée. Vérifier qu'un rejet avec une raison est consultable après modification ultérieure du corps.

### P2 — Un compte rendu réussi mentionnant une limite est traité comme un échec de service

**Localisation :** `scripts/claude_runner.py:69-87`.

La détection de limite recherche une expression dans l'ensemble stdout+stderr avant d'analyser le résultat JSON. Une revue réussie expliquant « handle rate_limit_error » correspond au motif et déclenche `rate_limited`, même avec code de sortie 0 et résultat `is_error:false`. Le heartbeat peut ensuite relancer un travail déjà terminé.

**Correction :** analyser en priorité la structure du résultat et le statut d'erreur ; ne classifier une limite qu'à partir d'une erreur effective de l'outil/service. Vérifier deux sorties synthétiques : succès qui cite `rate_limit_error` et erreur réelle de quota.

## Limites additionnelles à documenter ou corriger

- `parse_import`, ligne 65, appelle `request.get` avant de vérifier que `request` est un objet. Une trace avec `request: []` produit une exception de type plutôt qu'un rejet métier explicite. Les objets `payload` des transcripts méritent la même validation.
- La variante brute WebSocket avec `response.body: null` et `response.ws_events` n'est pas reconstruite ; une requête lisible suffit à faire réussir l'import, même si la réponse entière est omise. Documenter cette limite et recommander l'export claude-tap normalisé, ou refuser/avertir ce cas au lieu d'un succès partiel silencieux.
- L'épisode est actuellement une chaîne sur une note, sans entité avec identifiant, objectif et état. US-01 et la vision décrivent davantage. La synthèse produit doit soit obtenir cette capacité, soit annoncer clairement le regroupement initial par libellé et reporter l'entité épisode ; ne pas marquer US-01 entièrement satisfait par un simple champ texte.
- Les métadonnées de source ne constituent pas une preuve d'identité de l'auteur humain : `agent` est éditable. Décrire l'audit comme historique local, sans prétendre fournir une attestation cryptographique ou multiutilisateur.

## Conseils MCP vérifiés et transmis à l'intégrateur

Le [transport stdio officiel](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) utilise des messages JSON-RPC UTF-8 séparés par une nouvelle ligne ; stdout ne contient que le protocole, les logs vont sur stderr. Le client lance le processus ; EOF permet sa fermeture.

Le [cycle officiel](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle) commence par `initialize` avec version, capacités et informations client. Le serveur répond avec sa version, ses capacités et `serverInfo`, puis reçoit `notifications/initialized`. Il ne doit annoncer que les capacités mises en œuvre.

La [spécification des outils](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) définit `tools/list` et `tools/call`, un `inputSchema` objet et des résultats `content`. Une erreur métier/validation est un résultat avec `isError: true` ; un outil inconnu relève d'une erreur JSON-RPC. Ces règles ont été communiquées au chef d'orchestre. L'interopérabilité avec un vrai client nécessite une preuve distincte de cette lecture documentaire.

## Suivi

Le chef d'orchestre attribue les corrections et consigne leurs preuves. Cette revue ne clôt aucun finding et ne certifie aucun test. Une fois les corrections reçues, distinguer « code corrigé en lecture » de « scénario exécuté avec succès ».
