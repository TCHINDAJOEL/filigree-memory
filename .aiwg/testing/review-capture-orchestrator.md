# Revue indépendante de la capture — orchestrateur

Date : 16 octobre 2026. Lecture du premier jet Sonnet pendant l'intégration ; constats à confirmer sur la version terminée. Aucun test exécuté ici.

- **RC-01, haute — pensée interne.** Le repli Codex dans `Capture._fallback_line` prend tous les messages assistant sans filtrer `payload.channel == "analysis"`. Filtrer ce canal et les variantes de raisonnement interne, aussi dans l'extraction TAP. Les réponses visibles restent conservables. Ajouter un cas de régression qui vérifie l'absence du texte privé.
- **RC-02, haute — activation directe.** Le repli natif existe mais son défaut est `false`. Le besoin utilisateur inclut une commande Claude/Codex directe. Vérifier ce parcours puis activer le repli par défaut si sa déduplication est fiable ; expliquer précisément le délai et les limites des clients. Une fonctionnalité présente mais toujours désactivée ne satisfait pas le parcours principal demandé.
- **RC-03, haute — résolution explicite des conflits.** `_link` refuse plusieurs identifiants avant de consulter un rattachement explicite `tap:<session>`. L'interface peut donc proposer un rattachement sans effet pour `ambiguous_native_id`. Définir et tester un traitement explicite sûr, ou refuser clairement cette opération au lieu de confirmer un succès trompeur. Ne jamais résoudre automatiquement un conflit.
- **RC-04, moyenne — contrat Codex.** L'étude upstream décrit `x-codex-turn-metadata.thread_id` ainsi que `session_id`, mais `native_ids` ne lit que le second. Prendre en charge les deux et refuser leur divergence.
- **RC-05, moyenne — bornes de lecture.** `decode_payload` charge le blob entier avant le contrôle de taille ; borner la sélection SQLite comme pour le record. La référence doit vérifier strictement les champs de version, taille, hash et type, même si plusieurs références pointent le même hash. `NativeIndex` ne détecte pas une réécriture de fichier de même longueur via mtime ; éviter de conserver une ancienne correspondance de dossier dans ce cas.
- **RC-06, moyenne — provenance explicite.** Une liaison manuelle omet `cwd` dans l'événement. Le dossier cible connu du projet doit être conservé comme cible explicitement choisie, sans le présenter comme une preuve de dossier natif.

Constats interface préexistants : voir `../planning/integration-findings.md` (changement de projet asynchrone, libellé d'import et nouveau paquet à reconstruire).

À recontrôler indépendamment : verrouillage des commandes entre processus, interruption entre import et curseur, sessions en attente lors d'un changement de base TAP, erreurs malformées ne bloquant pas le moniteur, premier scan sans historique, exclusion du dossier de données, nouvelle activité native après une ancienne utilisation de TAP.

## Ajout pendant la passe fonctionnelle

- **RC-07, haute — crash avant sauvegarde des attentes.** Au premier jet comme après les correctifs initiaux, `Capture._save` écrit `state.json` (curseurs avancés) avant `pending.json`. Une panne entre ces deux remplacements perd les nouvelles clés en attente alors que le curseur empêche leur relecture. Le test crash après import ne couvre pas ce chemin. Écrire les attentes avant l'avancement des curseurs (puis accepter une relecture idempotente) ou utiliser un checkpoint atomique commun ; tester une interruption à cet endroit avec une session inconnue puis son rattachement. Faire aussi examiner les suppressions d'attentes lors de la résolution et le changement de DB. Ce constat doit être traité avant livraison.
