# Remediation — services (server.py, cli.py, mcp.py)

Date : 16 octobre 2026. Agent : Sonnet (services). Périmètre édité : `filigree/server.py`, `cli.py`, `mcp.py`, `tests/test_remediation_services.py`. Ce document n'affirme pas que le produit est prêt à publier : l'intégration et la vérification indépendante restent à faire.

## Exécuté

| Commande | Résultat |
| --- | --- |
| `python -m unittest discover -s tests -p test_remediation_services.py` | 26 tests, OK |
| `python -m unittest discover -s tests -p "test_[!r]*.py"` (suites préexistantes) | 136 tests, 1 échec : `test_store.StoreTests.test_history_validates_revision_filename_and_snapshot_identity` (module store, hors périmètre, travail d'un autre agent en cours) |
| `python -m unittest discover -s tests` (tout) | 193 tests, 17 échecs + 3 erreurs, tous dans `test_remediation_capture.py` (capture, hors périmètre) ; aucun dans mes tests ni dans `test_http`/`test_adapters` |

Les tests de ce fichier n'ont pas été vus échouer sur l'ancien code (pas de contrôle « rouge avant vert » exécuté) ; ils vérifient des comportements observables, dont des sous-processus réels.

Isolation : chaque serveur ou sous-processus reçoit `CLOUDTAP_DB`, `XDG_DATA_HOME`, `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `HOME`, `USERPROFILE` dans un dossier temporaire. Aucune lecture de `~/.claude`, `~/.codex` ou d'une base TAP réelle. Aucun appel Claude, aucune installation.

## Défauts

| ID | Correction (comportement prouvé) |
| --- | --- |
| C-4 / D-12 | `--no-capture` crée un `DisabledCapture` : aucun fichier, verrou, thread ni chemin de source. `GET /api/capture` renvoie un état statique (`disabled_by_server`, `tap.capability=disabled`, `roots={}`). Toute action sauf `stop` répond 409 « désactivée ». Test en mémoire avec pièges (`Capture`, `start`, `scan_once`, `probe`, `resolve_db_path`, `default_roots`, `NativeIndex` lèvent si appelés : 0 appel) et test en sous-processus (`serve --port 0 --no-capture` : start/enable/scan/fallback-on → 409, aucun projet créé malgré une transcription synthétique, ni `.capture` ni dossier TAP créé). |
| C-2 | Windows : `SO_EXCLUSIVEADDRUSE`, pas de `SO_REUSEADDR`. Un second `LocalServer` sur le même port lève `OSError`. Un second `serve` sort avec le code 1 et « Impossible d'écouter… », sans traceback ; le premier garde le port. |
| C-1 | `mcp.run` ré-encapsule les flux réels en UTF-8 (LF) ; `cli.main` reconfigure aussi stdin. Sous-processus réel, UTF-8 brut : titre `Décision café 日本語 😀` stocké à l'identique, dossier non ASCII retrouvé par `project_for_folder`, sortie sans CRLF. |
| C-3 | TOML Codex joint avec `\n` et chaînes TOML échappées (sans paires de substituts `\ud83d`). Sortie octets sans `\r\r`, `tomllib` l'accepte, dossier avec emoji restitué à l'identique. |
| Config lançable | Si le paquet n'est pas installé (hors site-packages), la config ajoute `env.PYTHONPATH` = racine source (JSON Claude et TOML Codex), avec `sys.executable`. Test : lancement de chaque entrée depuis un autre dossier avec `PYTHONPATH` vidé, réponse `initialize` reçue. |
| C-6 | `propose_memory` refuse corps ou titre vides/blancs et `agent` humain (human, humain, user, utilisateur, reviewer, relecteur, owner, me, moi, admin…, casse et espaces ignorés) ou vide. Statut toujours `proposed`. Aucun outil d'approbation (test). |
| C-7 | Budget invalide → 400 propre (HTTP, MCP, CLI : 500–100000) ; `action` non-chaîne → 400 ; `Content-Length` invalide → 400 ; JSON très imbriqué (corps et import) → 400 au lieu de 500 ; PUT/DELETE/OPTIONS/HEAD → 405 JSON avec CSP ; Host/Origin insensibles à la casse (le nom reste strict) ; `id` MCP null/liste/booléen → -32600 ; `name` d'outil liste → « Unknown tool » ; erreurs MCP/CLI sans repr `'Project not found'` ni traceback ; message d'erreur borné à 300 caractères sur une ligne ; `TypeError` → message générique. |
| P3 MCP | Ligne > 1 MiB : lecture bornée par `readline(MAX+1)`, refus -32600 puis le service continue (test). |
| P3 CLI | `--interval` nan/inf/-inf/1e999 → rejeté par argparse (code 2) pour `watch` et `capture run` ; `--port` hors 0–65535 rejeté. `watch` : une version illisible est signalée une seule fois puis ignorée jusqu'à changement (test : 1 message en 4,5 s avec `--interval 1`) ; `.txt/.md` traités comme `import` ; fichier non UTF-8 → message propre ; exception inattendue → « opération impossible (Type) » sans traceback. |

## Non modifié, volontairement ou hors périmètre

- **C-5** (entrée créée `accepted` via HTTP avec le jeton) : inchangé. Le formulaire humain de l'interface choisit le statut, et le jeton local est la frontière de l'interface locale, sans garantie d'identité distante. La gouvernance repose sur les points de revue explicites ; MCP, imports et capture restent des propositions. À trancher par l'architecte si le formulaire doit passer par un endpoint de revue distinct.
- Une entrée `superseded` encore modifiable par PATCH (C-7) : logique du store, non traitée.
- Les noms « humains » filtrés sont une liste fixe : un libellé comme « Human (approved) » passe. L'attribution MCP reste une déclaration non vérifiée.
- Non testé : Ctrl-C, push Git via HTTP, Linux/macOS (le chemin `SO_REUSEADDR` hors Windows n'a pas été exercé ici).

## Contrats à intégrer par la racine

1. `LocalServer(address, store, capture=None, capture_enabled=True, env=None)` et `serve(root, port, capture, env=None)` : `env` est transmis à `Capture(store, env)`. `serve` lève `ValueError` si le port est occupé.
2. UI (`app.js`, hors périmètre) : avec `disabled_by_server`, le bouton « Activer la capture » reçoit un 409 (toast d'erreur en français). Il faudrait masquer les contrôles quand `status.disabled_by_server` est vrai.
3. `tests/test_remediation_capture.py` et `test_store.py` échouent aujourd'hui sur des travaux en cours dans `capture.py`/`store.py` ; ce n'est pas lié à ces modifications.
4. E-2 (handoff/recherche), B-1, A-x : modules store/capture, non touchés.
