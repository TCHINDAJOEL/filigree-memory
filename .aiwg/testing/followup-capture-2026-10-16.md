# Suivi des constats de capture — Sonnet, 16 octobre 2026

Complète sans les remplacer [review-capture-orchestrator.md](review-capture-orchestrator.md) et [../planning/integration-findings.md](../planning/integration-findings.md), conservés comme preuves datées. **Statuts établis par lecture du code et des tests écrits ; aucun test n'a été exécuté pour ce suivi.** Un statut « corrigé en source » ne devient « vérifié » qu'avec le rapport d'exécution de Haiku.

| Constat | Statut en source | Où |
| --- | --- | --- |
| RC-01 pensée interne | Corrigé : blocs et canaux de raisonnement exclus dans les deux canaux ; test `test_private_analysis_is_excluded_natively_and_through_tap` | `tap_source.is_private`, `content_items`, `capture._fallback_line` |
| RC-02 activation directe | Corrigé : repli natif activé par défaut, déduplication inter-canaux bornée | `default_settings`, tests `ChannelSwitchingTests` |
| RC-03 conflit explicite | Corrigé : le choix explicite `tap:<session>` est lu avant le refus ; jamais de résolution automatique | `Capture._link`, `ExplicitConflictTests` |
| RC-04 contrat Codex | Corrigé : `session_id` et `thread_id` lus, divergence = conflit | `tap_source.native_ids` |
| RC-05 bornes | Corrigé : taille de blob bornée dans SQLite, références strictes, réécriture à longueur égale détectée | `decode_payload`, `NativeIndex.refresh` |
| RC-06 provenance explicite | Corrigé : `target_folder` + `target_basis`, sans prétendre à une preuve native | `Capture._events`, `_fallback_line` |
| F-UI-01 changement de projet | Corrigé en source : `state.switching`, `assertStable`, sélecteur sur la cible ; la vue Capture n'est plus reconstruite par un rafraîchissement | `app.js` |
| F-UI-02 libellé | Corrigé : `events.imported` → « Traces importées » | `app.js` |
| RC-07 ordre de sauvegarde | Corrigé en source (voir [final-fixes.md](final-fixes.md), P1-1) : `pending.json` est écrit avant `state.json` ; test de panne entre les deux fichiers. **Non exécuté.** | `Capture._save`, `CheckpointOrderTests` |
| F-PACKAGE-01 paquet | Résolu par l'exécution queue-3 (wheel reconstruit, `verify_package.py` PASS) ; à refaire sur le nouveau wheel après les corrections finales | — |

## Exigences de justesse ajoutées (suite de la revue de phase 0)

1. **Rattachements `tap:ID` portés par la base.** Stockés `tap:ID@<db_key>` ; seuls ceux de la base courante sont actifs ; un rattachement d'avant cette portée (`tap:ID` nu) n'est jamais appliqué. Documenter un rattachement accidentel entre bases n'aurait pas suffi. Tests : `ScopedMappingTests`.
2. **Repli natif sans perte irréversible.** Le décalage n'avance pas au-delà d'une ligne dont la session n'est pas encore résolue. Retenue bornée (100 fichiers, dépassement compté et signalé), visible en attente sans texte brut, reprise dans l'ordre sans doublon. Pause et exclusion sont des sauts délibérés. Tests : `HeldNativeTests`.

## Constats propres à cette passe

- `canonical_folder` : sous Windows, `manquant\..` était accepté parce que le système réduit le chemin avant le test d'existence (échec `test_folders`). Cause réelle corrigée, test inchangé.
- Vue Capture : `captureAction('link')` appelle `refresh()` après la mise à jour de l'état, ce qui reconstruisait la vue et effaçait la saisie du formulaire d'exclusion (échec Playwright). Cause réelle corrigée, test inchangé.

## Ouvert / non établi

- Aucun essai avec un client réel avant l'exécution de `verify_live_capture.py` ; ce script ne prouve qu'un échange Claude Code (haiku) sur une machine.
- Les formats réels de transcription Claude Code / Codex peuvent différer des fixtures synthétiques.
- La capture d'écran du README est présente (`.github/assets/workbench.png`, ajoutée par l'orchestrateur) ; `npm test` la régénère.
- Les corrections finales (P1/P2 de la revue Opus) sont consignées dans [final-fixes.md](final-fixes.md) ; elles ne sont vérifiées que par l'exécution de Haiku.
