# Corrections finales après la revue Opus — Sonnet, 16 octobre 2026

Résolutions des constats de [review-capture-opus.md](review-capture-opus.md) (conservé comme preuve datée, non réécrit). **Tout ce qui suit est établi par lecture du code et des tests écrits. Aucun test, build ni appel live n'a été exécuté par l'auteur** ; seule l'exécution de Haiku fera passer un statut de « corrigé en source » à « vérifié ». Le gate appartient à Codex.

Les constats ont été recontrôlés sur le code courant avant toute modification.

| Constat | Verdict | Résolution | Test de régression |
| --- | --- | --- | --- |
| P1-1 RC-07 | Réel (`_save` écrivait `state.json` avant `pending.json`) | `_save` écrit `pending.json` d'abord ; une panne entre les deux fichiers rejoue les enregistrements (index de session dédupliqués, import dédupliqué par URI) au lieu de perdre des clés. Le changement de base TAP passe par le même `_save` (les clés en attente de l'ancienne base sont déjà en quarantaine, écrite avant tout changement de `db_key`) | `CheckpointOrderTests` : panne injectée à la 2ᵉ écriture, session inconnue, redémarrage, puis rattachement qui importe l'enregistrement |
| P1-2 suivi | Réel | Ligne RC-07 ajoutée à `followup-capture-2026-10-16.md` | — |
| P2-1 bascule du repli | Réel | `set_native_fallback` écrit un fichier `hold-fallback` : seul `fallback_hold` est levé, les curseurs TAP ne sautent plus | `test_toggling_the_native_fallback_does_not_discard_tap_activity` ; `test_a_global_pause_still_skips_tap_activity` garde la pause globale |
| P2-2 pause et lignes retenues | Réel | Les lignes retenues avant une pause ou désactivation globale sont rattrapées ; seul l'intervalle de pause est sauté. La taille de chaque fichier retenu est enregistrée au moment de la pause (fichier `hold`, ou premier scan en pause) ; à la reprise l'intervalle [début de pause, taille à la reprise) est mémorisé comme trou (`fallback.gaps`, 20 au plus par fichier) et les lignes qui le chevauchent sont sautées et comptées (`paused`), les autres restent lues dans l'ordre. Plusieurs pauses avant la résolution s'additionnent sans perdre de ligne retenue entre elles | `PauseAndHomeTests` : pause vue par le moniteur, et pause jamais vue (seul le fichier `hold`) |
| P2-3 racine Git | **Partiellement déjà couvert** : `canonical_folder` refuse déjà le dossier personnel et une racine de lecteur, et `_resolve_native` retombe alors sur le dossier lui-même. Faille restante : un dépôt Git **au-dessus** du dossier personnel (ex. `C:\Users`) | `_contains_home` : une racine Git qui est ou contient le dossier personnel est ignorée | `test_a_git_repository_above_the_home_folder_…` ; `test_home_and_drive_roots_are_never_project_folders` fige le refus existant |
| P2-4 démarrage direct | Documenté et **testable en réel** | README : le démarrage direct n'est plus présenté comme vérifié ; `verify_live_capture.py --native-direct` (un appel Haiku, `claude` lancé sans claude-tap) est prêt mais **non exécuté**. Reste ouvert au gate tant que Haiku ne l'a pas exécuté | script lui-même |
| P2-5 brouillon d'import | Réel | Changer de projet avec du texte dans le formulaire d'import demande confirmation ; un refus restaure le sélecteur | Playwright : `switching project asks before discarding an import draft…` (non exécuté) |
| P2-6 docs périmées | Réel | `verification.md` pointe vers ce document et précise que les résultats queue-3 précèdent ces corrections (la section queue-3 est conservée) ; F-PACKAGE-01 mis à jour | — |
| P2-7 `git add` | Réel (limite de ligne de commande) | `git add` par blocs de 8000 caractères (`ADD_CHUNK_CHARS`) | `test_git_checkpoint_adds_in_bounded_chunks…` |
| P2-8 `tap:` + historique | Réel | `_link` expose `mapped_keys` ; l'historique filtre sur l'appartenance, plus sur la première clé | `HistoryWithNativeMappingTests` |

## Autres changements

- `scripts/verify_package.py` refuse un wheel plus ancien que les sources, choisit le plus récent par date, et vérifie que le paquet contient la confirmation de brouillon et le `hold-fallback`.
- `scripts/verify_live_capture.py --native-direct` : mode isolé, un appel Haiku, `claude` sans claude-tap, `CLAUDECODE` (et une URL de base loopback injectée par un claude-tap parent) retirés pour ce seul enfant ; ligne de base d'abord ; seule la transcription nommée exactement `<session_id>.jsonl` est copiée dans la racine native isolée, jamais affichée ; contrôle exact des métadonnées de provenance, du marqueur, du statut `proposed` et de l'absence de doublon sur deux nouveaux scans. Les variables d'environnement globales et les configurations ne sont pas modifiées ; l'appel utilise toutefois la configuration Claude réelle de l'utilisateur (authentification), qui ne peut pas être isolée.
- `scripts/verify_live_handoff.py` (nouveau, opt-in, **non exécuté**) : voir son en-tête. Il prouve au mieux un client réel, pas une injection automatique générale.

## Limites connues

- Le test P2-2 couvre un fichier retenu ; une pause jamais observée et sans fichier `hold` (réglage modifié à la main hors CLI) enregistre la taille au premier scan en pause, avec la précision d'un intervalle de scan.
- Une ligne partielle écrite avant la pause et complétée pendant celle-ci est comptée dans l'intervalle sauté.
- La corruption simultanée de `pending.json` et `state.json` n'est pas traitée.
