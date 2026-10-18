# Sondes D9 — sources réelles du poste de développement

Date : 17 octobre 2026. Exécutant : orchestrateur (Opus). Commande : `python -c "from filigree.probe import run_probe; …"` sur le poste Windows 10 de l'utilisateur, **en lecture seule**. La sortie se limite à des comptages et des noms de champs, sans chemin de conversation ni contenu.

| Collecteur | Statut | Sessions | Avec `cwd` | Dossiers distincts | Remarques |
| --- | --- | --- | --- | --- | --- |
| `claude_code` | ok | 99 | 99 | 26 | 19 fichiers de sous-agents ; `sessionId, cwd, entrypoint, version, gitBranch, timestamp` présents dans 99/99 |
| `claude_desktop` | ok | 17 | 17 | 9 | **`cliSessionId` présent dans 9/17 seulement** : 8 sessions Desktop ne peuvent pas être reliées à une transcription par identifiant exact |
| `codex_state` | ok | 187 | 187 | 39 | Colonnes requises et facultatives présentes ; table `thread_spawn_edges` présente |
| `codex_rollout` | ok | 10 | 10 | 3 | **177 rollouts `.zst` non lus** (`zstandard` absent) ; `parent_thread_id` dans 6/10 |
| `claude_tap` | ok | (97 sessions tap) | — | — | Capacité seulement ; contenu toujours lu par le collecteur v0.1 |

## Conclusions

- Les quatre sources de découverte sont exploitables sur ce poste. Le `cwd` est connu pour 313 sessions sur 313.
- Pour Codex, la base d'état est **indispensable** : la grande majorité des rollouts est compressée. Les sessions anciennes ne sont pas rattrapées (D11). Les sessions actives écrivent des rollouts `.jsonl` non compressés, lisibles.
- Pour Claude Desktop, une session sans `cliSessionId` reste affichée avec son `cwd` (métadonnée de l'application). Son **contenu** n'est capturé que par la transcription Claude Code correspondante, quand elle existe.
- Limite : un seul poste, une seule date. Les versions des outils n'ont pas été relevées par la sonde.
