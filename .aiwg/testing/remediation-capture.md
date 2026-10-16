# Remédiation — module capture (B-2 à B-7 et P3 capture)

Date : 16 octobre 2026. Auteur : agent Sonnet (périmètre : `capture.py`, `tap_source.py`, `native_index.py`, `tests/test_remediation_capture.py`). **Ce document ne déclare pas la version prête à publier** : l'intégration et la vérification indépendante restent à faire. Le GO précédent reste invalide.

## Isolation des tests

Chaque test crée une mémoire, une base claude-tap et des racines de transcriptions synthétiques dans un dossier temporaire, et les nomme explicitement dans `capture.json` (`tap.db`, `roots`). Aucun moniteur ni `status()` par défaut n'est instancié, aucune vraie source n'est lue. Aucun appel Claude, aucune installation, aucun commit. Les données de `agentC` n'ont pas été lues.

## Exécutions (état final)

| Commande | Résultat |
| --- | --- |
| `python -m unittest discover -s tests -p test_remediation_capture.py` | 27 tests, OK |
| `python -m unittest discover -s tests -p test_capture.py` | 80 tests, OK (aucune régression) |
| `python -m unittest discover -s tests -p test_adapters.py` | 13 tests, OK |
| `python -m unittest discover -s tests -p test_folders.py` | 8 tests, OK |
| `python -m unittest discover -s tests -p test_http.py` | 8 tests, OK |

Avant les corrections, les nouveaux tests donnaient 16 échecs et 4 erreurs sur 27 (les autres : cas déjà couverts ou rendus vrais par un changement de `store.canonical_folder` fait entre-temps par un autre agent).

## Défauts : confirmation, cause racine, correction, preuve

- **B-2** (confirmé). `visible_text` supprimait tout message commençant par une balise injectée. Maintenant seuls les blocs balisés sont retirés (`environment_context`, `system-reminder`, `ide_*`, `command-*`, `local-command-*`, `permissions`, `developer`, `instructions`…), le texte de l'utilisateur autour est conservé. Un bloc jamais fermé est supprimé jusqu'à la fin (son étendue est inconnue). L'en-tête `# AGENTS.md instructions` reste supprimé en entier. Le raisonnement caché n'est jamais exposé (chemin `is_private` inchangé). Tests : `InjectedContextTests` (unité, TAP, natif Claude, Codex).
- **B-3** (confirmé). Un nom de dossier de plus de 160 caractères faisait lever `ValueError` hors du `try`. Corrections : nom du projet tronqué à 160 ; `ValueError` de création → `cwd_refused` (session en attente, jamais perdue) ; toute exception inattendue de résolution → `resolve_error` (retenue) ; exception de ligne → ligne perdue **et comptée** (`malformed.native_line_error`) ; exception d'enregistrement TAP → `malformed.processing_error`. Aucune ne bloque les sessions suivantes. Tests : `IsolationTests` (natif, TAP, ligne défaillante).
- **B-7** (partiellement déjà traité par le store, voir « Contrat »). Côté capture : refus de création automatique si le dossier est égal à, ou au-dessus de, un point partagé (temp, dossier personnel et ses parents, `/tmp`, `/home`, `Program Files`…), ou sous le dossier Windows ou `/etc`… Un dépôt Git situé sur un tel point n'est plus pris comme racine. Un projet **déjà** lié à un tel point (créé par une ancienne version) n'absorbe plus ses sous-dossiers : ils obtiennent leur propre projet. Les sous-projets légitimes (sous temp ou sous le dossier personnel, dépôt Git imbriqué) fonctionnent. Tests : `GenericRootTests` (6 cas, natif et TAP).
- **B-4** (confirmé). `link file:…` répondait `replayed: true` sans effet. Maintenant : la clé `file:` doit désigner une transcription réellement retenue (sinon `CaptureError` claire, aucun rattachement écrit) ; le rattachement place le rollout sans `session_meta` ou à `session_meta` multiples, dans l'ordre, avec provenance `link: explicit` et `native_id = file:…`. `link` renvoie aussi `still_pending`. Tests : `FileLinkTests`.
- **B-5 / B-6** (confirmés). Un NUL ou un surrogate isolé faisait rejeter l'événement, et l'UTF-8 invalide faisait perdre la ligne, sans compteur. Maintenant : NUL et surrogates → U+FFFD, compté (`skipped.invalid_text_repaired`, `fallback_` côté natif) ; UTF-8 invalide natif → ligne lue avec remplacement, comptée une seule fois (`malformed.native_invalid_utf8`) ; UTF-8 invalide dans la base TAP → l'ancien comportement rendait **toute la base « corrupt » à chaque cycle** ; maintenant décodage tolérant, compté (`malformed.tap_invalid_utf8`), le curseur avance. Les lignes JSON invalides sont aussi comptées (`native_invalid_json`). Les refus du store laissent une notice `event_rejected` (raison, jamais le contenu). Tests : `InvalidTextTests`.
- **Ligne de base** (P3, B-10). Un fichier découvert après la ligne de base dont la date de modification précède la ligne de base (de plus de 2 s) est de l'historique : il est positionné à sa taille, compté (`skipped.native_history_ignored`) avec une notice. Un fichier né après la ligne de base reste lu en entier. La ligne de base est horodatée (`fallback.baselined_at`, remise à jour à chaque reprise après pause). Tests : `BaselineTests`.
- **Compteur `redactions`** (P3). Alimenté à partir du retour de `import_events` (`counters.redactions`). Test : `RedactionCounterTests` (il reflète ce que le store masque).
- **B-8** (P3, dans mon module). `_safe_interval` : nan, inf, 1e400, ≤ 0 ou non numérique → valeur finie bornée à [0,5 ; 3600] (défaut 3). Appliqué à la boucle du moniteur. Test : `IntervalAndPathTests`.
- **B-9** (P3). `link`, `set_paused` : projet inconnu → `UnknownProject` (une `CaptureError` qui reste un `KeyError`, message français lisible) ; identifiant invalide → message français ; `link tap:absente --import-history` → refus clair ; `unlink` valide la clé. Test : `test_link_validations_name_the_problem_in_french`.
- **P3 `\\?\`**. Le préfixe étendu Windows est retiré avant résolution du dossier. Test (Windows) : `test_an_extended_length_cwd_is_resolved_like_the_plain_one`.

## Préservé (couvert par les 80 tests existants, repassés)

Provenance exacte, ordre de checkpoint (clés en attente avant curseur), lignes retenues pendant une pause, dédoublonnage entre canaux (registres tap/natif), mise en quarantaine à changement de base.

## Contrat et coordination (sans modifier un autre module)

- **store** : `canonical_folder` refuse désormais les points partagés exacts (changement d'un autre agent, vu à la relecture). Il ne refuse pas les **ancêtres** de temp ou du dossier personnel, ni les dépôts Git qui les contiennent ; la capture le fait elle-même. Souhaitable : une fonction publique du store (`is_generic_folder`) pour éviter deux listes.
- **cli** (hors périmètre) : `--interval nan|inf` est neutralisé dans la capture, mais l'analyse de l'argument et l'affichage du `KeyError` restent à revoir côté `cli.py`. `UnknownProject` s'affiche proprement via `str()`.
- **server** : `link` renvoie un champ supplémentaire `still_pending` ; le `--no-capture` défectueux (C-4/D-12) n'est pas dans mon périmètre.
- **A-4 / store** : les clés de dossier `C:\x` / `\\?\C:\x` sont déjà unifiées par le store ; la capture normalise aussi côté lecture.

## Éléments non résolus ou limites

- Un vieux transcript dont la date de modification est **récente** (touché, synchronisé) est considéré comme nouveau : la date de modification est le seul indice fiable sans lecture du contenu.
- Les sessions TAP nouvelles après la ligne de base sont importées entières (aucune règle équivalente, la base n'ayant pas de date de création fiable).
- `redactions` ne compte que ce que le store déclare ; la couverture du masquage elle-même (B-1) relève du store.
- Le compteur de textes invalides du décodeur TAP est global au processus : deux moniteurs dans un même processus pourraient se partager le décompte.
- Nom court 8.3 : non reproduit ni modifié.
- Non testés : transcriptions réelles Claude/Codex, flux SSE réels, WAL sous charge, tests de ressources à 3000 transcriptions.
