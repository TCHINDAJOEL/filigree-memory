# Intégration claude-tap — faits vérifiés et contrat limité

Recherche primaire : 15 octobre 2026. Auteur et synthétiseur : agent produit/architecture. Statut : contrat révisé après lecture de l'adaptateur ; tests de livraison à confirmer séparément. Les liens `main` peuvent évoluer ; cette note ne promet pas une compatibilité avec toute version future.

## Entrée recommandée

Le [code officiel de l'export](https://github.com/liaohch3/claude-tap/blob/main/claude_tap/export.py) accepte une ancienne trace JSONL ou une session stockée et propose les formats `markdown`, `json`, `html`, `compact`, `prompt-md`. Le format par défaut est **compact**. Pour l'adaptateur simple de Filigree, demander explicitement JSON :

```sh
claude-tap export --session-id <identifiant> --format json -o session.json
```

Cet export est un tableau JSON. Chaque élément contient `turn`, `timestamp`, `duration_ms`, `model`, `messages` et `response` (`content`, `usage`, `stop_reason`) ; `system` et `tools` sont optionnels. Il passe par la normalisation du visualiseur avant extraction. Les exemples publiés dans Filigree doivent être synthétiques et ne contenir aucune conversation privée.

## Anciennes traces et variantes

Le [writer actuel](https://github.com/liaohch3/claude-tap/blob/main/claude_tap/trace.py) écrit dans le store SQLite. Il ne faut donc pas supposer que chaque session actuelle produit spontanément un nouveau fichier `.traces/*.jsonl`. Les anciennes traces brutes JSONL contiennent généralement les enveloppes `request.body` et `response.body`, tandis que l'export JSON les a aplaties.

La [fixture officielle OpenAI Responses](https://github.com/liaohch3/claude-tap/blob/main/tests/fixtures/openai_responses_trace.jsonl) montre une variante WebSocket : `request.body.input`, `request.body.instructions`, `response.body: null` et `response.ws_events`. Le texte final peut être dans `response.completed.response.output`. Un parseur limité à `messages`/`content` ne doit pas se présenter comme compatible avec toutes les traces brutes Codex. L'export JSON normalisé est le parcours documenté ; les branches brutes prises en charge doivent être couvertes par des fixtures propres à Filigree.

Les bundles `.ctap.json` sont un format compact distinct : la v0.1 les refuse et explique de réexporter avec `--format json`. Elle refuse aussi explicitement les événements bruts WebSocket au lieu d'importer une moitié de conversation. Les variantes de transcript ou d'export normalisé acceptées doivent contenir les messages finaux, puis être couvertes par les tests ; aucune reconstruction universelle d'événements réseau n'est annoncée.

## Capture et gouvernance

Le [README officiel](https://github.com/liaohch3/claude-tap#quick-start) documente `claude-tap` pour lancer Claude Code et les arguments du client après `--`. Les autres clients ont leurs options propres. La prise en charge annoncée par claude-tap n'est pas une validation bout en bout de Filigree pour chacun de ces clients. Les événements SSE/WebSocket bruts ne sont conservés qu'avec l'option appropriée de capture ; le produit ne reconstruit pas un contenu jamais enregistré.

L'import peut retrouver du texte, des observations et des justifications exprimées. Il ne récupère pas des pensées internes cachées et ne déduit pas automatiquement une autorisation humaine. Il produit des observations proposées, sans synthèse LLM. Les historiques répétés sont dédupliqués par identité de contenu dans leur contexte d'import ; les limites de cette identité doivent rester visibles, notamment pour deux messages identiques réellement répétés. La date source disponible est conservée comme provenance, distinctement de la date d'import. Les blocs inconnus sont des données sans autorité.

Le parcours CLI `watch` surveille un seul fichier JSON/JSONL explicitement choisi. Il ne capture pas les clients ni ne lance Claude Code. Les originaux ne sont pas copiés automatiquement ; les extraits stockés dans la mémoire peuvent se retrouver dans les exports/checkpoints. L'adaptateur et le store partagent une limite de 1 000 événements ; une expansion au-delà de cette limite est rejetée avant persistance.

## Capture automatique (mise à jour du 16 octobre 2026)

Le parcours principal n'est plus l'import d'un export : le moniteur de Filigree lit directement la base SQLite de claude-tap, **en lecture seule et sans importer `claude_tap`**. Contrat (décision : [ADR-0002](ADR-0002-automatic-project-capture.md), révision 3) :

- **Source** : schéma `user_version = 4` avec les colonnes requises ; toute autre version est `unsupported_schema` et rien n'est lu. Chemin : réglage Filigree, `CLOUDTAP_DB`, `XDG_DATA_HOME`, puis `~/.local/share/claude-tap/traces.sqlite3`. Un enregistrement compact est restitué seulement si version, nature, empreinte et taille concordent ; sinon il est rejeté entier.
- **Pas de dossier dans tap** : le dossier vient d'une transcription native dont l'identifiant de session est **égal** à celui que déclare l'enregistrement (en-tête, `metadata.user_id`, métadonnées de tour Codex). Rien n'est lié par proximité de temps, nom ou texte. Ces identifiants sont des déclarations locales, pas une authentification.
- **Sans tap** : pour un client lancé directement, les nouvelles lignes complètes de sa transcription locale sont lues (repli natif, activé par défaut) ; la déduplication entre canaux est bornée et expire. Une session non résolue est retenue, pas ignorée.
- **Collecté** : texte visible, appels et résultats d'outils bornés, échecs HTTP. **Non collecté** : raisonnement caché, instructions système, blocs injectés. Tout est proposé, avec provenance (base, session tap, index, empreinte, identifiant natif, dossier, mode de lien).
- **Rattachement explicite** : `tap:<session>` est propre à la base choisie ; un identifiant natif ne l'est pas.
- **Non couvert** : Claude Desktop (conversation), Claude sur le web, tout client sans transcription locale ni passage par claude-tap, WebSocket brut et bundles `.ctap.json` (toujours refusés à l'import).

## Niveau de preuve attendu pour la livraison

| Affirmation | Preuve requise |
| --- | --- |
| JSON exporté accepté | Fixture synthétique conforme à `_export_json`, import et contenu visibles |
| JSONL brut accepté | Fixture par famille de format réellement implémentée |
| Réimport idempotent | Deux imports, absence de nouveaux doublons |
| Provenance conservée | Note → source et extrait consultables |
| Reprise entre clients | Transport MCP testé ; essai d'un vrai client étiqueté séparément |
| Surveillance contrôlée | Commande CLI sur un fichier choisi ; pas de claim de capture globale ni de lancement d'agent |
| Capture automatique par dossier | Tests synthétiques exécutés (schéma v4 écrit à la main, transcriptions synthétiques) ; l'essai live `verify_live_capture.py` est un seul échange, étiqueté séparément |
