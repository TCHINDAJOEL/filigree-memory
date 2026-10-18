# Prise en main de Filigree, application par application

> Ce guide est fait pour **démarrer maintenant**. Copiez les commandes dans l'ordre : l'installation commune (5 minutes), puis la section de chaque application que vous utilisez. Pour comprendre le fonctionnement en détail, voir le [guide complet](README.md).

![Ce que Filigree fait pour chaque application](images/schema-applications.svg)

| Vous utilisez… | Filigree **observe** vos sessions | L'agent **lit** la mémoire (MCP) | Section |
| --- | --- | --- | --- |
| Claude Code (terminal, VS Code, JetBrains) | Oui | Oui | [A](#a-claude-code) |
| Claude Desktop (onglet **Code**) | Oui, via la transcription Claude Code | Oui | [B](#b-claude-desktop) |
| Claude Desktop (conversation) | Non | Oui | [B](#b-claude-desktop) |
| Codex CLI | Oui | Oui | [C](#c-codex-cli) |
| Application Codex (Codex Desktop, extension VS Code) | Oui (mêmes fichiers que la CLI) | Oui (même configuration) | [D](#d-application-codex-et-extension-vs-code) |
| claude.ai, ChatGPT (navigateur ou application) | Non | Non | [E](#e-claudeai-et-chatgpt) : import de vos exports |
| Autre client MCP (Cursor, Windsurf…) | Non | Oui, configuration générique | [F](#f-autres-clients-mcp) |

## 0. Installation commune (une seule fois)

```sh
git clone https://github.com/TCHINDAJOEL/filigree-memory.git
cd filigree-memory
python -m pip install .
```

Choisissez **un** dossier de données et gardez-le partout.

**Windows (PowerShell) :**

```powershell
setx FILIGREE_DATA_DIR "$HOME\FiligreeMemory"     # permanent ; rouvrez le terminal ensuite
filigree setup --root "$HOME\code"                 # dossiers que Filigree peut observer
filigree create "Mon projet" --folder "$HOME\code\mon-projet"
filigree service install                           # démarrage automatique à l'ouverture de session
filigree agent                                     # ou lancez-le tout de suite (http://127.0.0.1:7820)
```

**macOS / Linux :**

```sh
echo 'export FILIGREE_DATA_DIR="$HOME/FiligreeMemory"' >> ~/.zshrc   # ou ~/.bashrc, puis rouvrez le terminal
filigree setup --root ~/code
filigree create "Mon projet" --folder ~/code/mon-projet
filigree service install
filigree agent
```

Vérifiez :

```sh
filigree status        # "agent": l'adresse de l'agent ; "allowed_roots": vos racines
filigree probe         # quelles applications ont des sessions lisibles sur ce poste
```

Ouvrez **http://127.0.0.1:7820**. Votre projet est là ; il se remplira à la première session.

> `filigree service install` est facultatif et réversible (`filigree service uninstall`). Sans lui, lancez `filigree agent` vous-même dans un terminal que vous laissez ouvert.

## A. Claude Code

Claude Code écrit ses transcriptions dans `~/.claude/projects/`. Filigree les lit en lecture seule, sans rien configurer d'autre.

**1. Travailler.** Lancez Claude Code **dans le dossier du projet** :

```sh
cd ~/code/mon-projet
claude
```

Dans les extensions VS Code et JetBrains, ouvrez le dossier du projet comme espace de travail. L'activité apparaît dans **Activité** quelques secondes plus tard, et la fiche de session arrive dans **Connaissances** 10 minutes après la fin.

**2. Donner la mémoire à Claude (MCP), une fois pour toutes :**

```sh
filigree mcp-config --client claude --command
```

Copiez puis exécutez la ligne affichée. Elle a cette forme :

```sh
claude mcp add --scope user filigree -- python -m filigree --data-dir /chemin/FiligreeMemory mcp
```

Avec `--scope user`, le serveur est disponible dans tous vos projets. Il ne montre que le projet du dossier où Claude travaille : Claude Code lui transmet ses dossiers de travail (roots MCP), ce qui a été vérifié en réel. Vérifiez avec `claude mcp list`, puis demandez par exemple à Claude : *« Utilise Filigree pour me résumer les décisions actuelles de ce projet. »*

**3. Contexte automatique au démarrage (optionnel) :**

```sh
filigree hooks install --client claude --inject --dry-run   # lisez le diff
filigree hooks install --client claude --inject             # appliquez (sauvegarde automatique)
```

Chaque nouvelle session Claude Code reçoit alors les connaissances **acceptées** du projet. Un signal de fin de session déclenche aussi la fiche de session immédiatement. Pour annuler : `filigree hooks uninstall --client claude`.

## B. Claude Desktop

**Onglet « Code ».** Il fait tourner Claude Code : ses sessions sont observées via la transcription Claude Code (section A), à condition de choisir le dossier du projet comme dossier de travail. Filigree lit les métadonnées de Claude Desktop (`claude-code-sessions`) mais jamais le contenu des conversations.

**Conversations classiques.** Elles ne sont pas observées, mais Claude peut **lire et proposer** dans la mémoire via MCP.

Claude Desktop ne lance pas le serveur depuis votre projet. Indiquez donc le projet explicitement :

```sh
filigree mcp-config --client claude-desktop --project-folder ~/code/mon-projet
# ou, pour donner accès à tous vos projets :
filigree mcp-config --client claude-desktop --all-projects
```

Copiez le bloc JSON affiché dans le fichier de configuration de Claude Desktop :
- **Windows :** `%APPDATA%\Claude\claude_desktop_config.json`. Pour la version Microsoft Store, le fichier peut se trouver sous `%LOCALAPPDATA%\Packages\Claude_…\LocalCache\Roaming\Claude\`. Le plus simple : *Paramètres → Développeur → Modifier la configuration*.
- **macOS :** `~/Library/Application Support/Claude/claude_desktop_config.json`.

Si le fichier contient déjà une section `mcpServers`, ajoutez-y seulement l'entrée `"filigree": {…}`. Quittez complètement Claude Desktop, puis relancez-le : les outils Filigree apparaissent dans le menu des outils.

```json
{
  "mcpServers": {
    "filigree": {
      "command": "python",
      "args": ["-m", "filigree", "--data-dir", "C:\\Users\\vous\\FiligreeMemory", "mcp", "--project-folder", "C:\\Users\\vous\\code\\mon-projet"]
    }
  }
}
```

## C. Codex CLI

Codex écrit ses sessions dans `~/.codex/sessions/` et son index dans `~/.codex/state_5.sqlite`. Filigree lit les deux en lecture seule. Les fils anciens, dont Codex a supprimé le fichier de session, se récupèrent avec `filigree import-codex-history` (voir plus bas).

**1. Travailler :**

```sh
cd ~/code/mon-projet
codex
```

**2. Donner la mémoire à Codex (MCP) :**

```sh
filigree mcp-config --client codex --command
# copiez puis exécutez la ligne affichée, de la forme :
codex mcp add filigree -- python -m filigree --data-dir /chemin/FiligreeMemory mcp
codex mcp list
```

Vous pouvez aussi coller le bloc de `filigree mcp-config --client codex` dans `~/.codex/config.toml`.

> Le périmètre automatique n'a pas été vérifié en réel avec Codex. Si Codex répond « outside this MCP server's scope », ajoutez le projet explicitement : `filigree mcp-config --client codex --command --project-folder ~/code/mon-projet`. Vous pouvez aussi ouvrir tous les projets avec `--all-projects`.

**3. Signal de session (optionnel) :**

```sh
filigree hooks install --client codex --dry-run
filigree hooks install --client codex
```

Ce hook ajoute un `notify` à `~/.codex/config.toml`. Si vous en avez déjà un, Filigree refuse de le remplacer. Ce hook n'injecte aucun contexte : avec Codex, c'est MCP qui donne accès à la mémoire.

## D. Application Codex et extension VS Code

L'application Codex et l'extension VS Code enregistrent leurs sessions dans **les mêmes fichiers** `~/.codex` que la CLI. Sur le poste de test, les sessions de l'application y apparaissent avec l'origine « Codex Desktop ». Filigree les observe donc **sans configuration supplémentaire** : il suffit d'ouvrir le dossier du projet dans l'application.

Pour la mémoire, la configuration MCP de la section C (`~/.codex/config.toml`) est partagée par la CLI, l'application et l'extension. Vérifiez dans les réglages MCP de l'application que le serveur `filigree` apparaît, et redémarrez l'application si besoin.

> L'effet du hook `notify` dans l'application n'a pas été vérifié. Les fiches de session arrivent de toute façon après 10 minutes d'inactivité.

## E. claude.ai et ChatGPT

Ces services s'exécutent dans le navigateur ou dans leur application, et Filigree ne peut ni les observer ni leur donner accès à la mémoire locale. En revanche, vous pouvez **importer vos conversations** :

1. **Exporter.**
   - ChatGPT : *Paramètres → Contrôles des données → Exporter les données*.
   - claude.ai : *Settings → Privacy → Export data*.
   - Vous recevez un lien vers une archive `.zip`.
2. **Importer**, en choisissant toujours le projet explicitement :

```sh
filigree projects                                          # repérez l'ID du projet
filigree import-export ~/Downloads/export.zip --project <ID>
```

Chaque message devient une **proposition** à examiner. Réimporter la même archive ne crée aucun doublon.

## F. Autres clients MCP

Tout client compatible MCP en **stdio** peut utiliser Filigree. Configurez-le avec :

- **Commande :** `python`
- **Arguments :** `-m filigree --data-dir <votre dossier de données> mcp`
- **Périmètre :** ajoutez `--project-folder <dossier du projet>` ou `--all-projects` si le client ne lance pas le serveur depuis le dossier du projet.

`filigree mcp-config --client claude-desktop --all-projects` affiche un bloc JSON `mcpServers` que la plupart des clients acceptent tel quel.

## Votre routine au quotidien

| Moment | Action |
| --- | --- |
| Vous ouvrez votre session | Rien à faire si `filigree service install` est fait. Sinon, lancez `filigree agent` |
| Vous travaillez | Lancez Claude Code ou Codex **dans le dossier du projet** |
| En cours de route | **Activité** : qui fait quoi, et les chevauchements entre sessions |
| En fin de journée | **Connaissances → à examiner** : acceptez, écartez ou corrigez les fiches de session et les propositions |
| Vous passez la main | **Reprise** (copier ou télécharger) ; l'agent suivant lit aussi la mémoire par MCP |

## Les dix commandes à retenir

```sh
filigree agent                                   # tout faire tourner (interface + capture + journal)
filigree status                                  # qu'est-ce qui tourne, qu'est-ce qui est installé ?
filigree setup --root DOSSIER                    # où Filigree a le droit d'observer
filigree create NOM --folder DOSSIER             # un projet = un dossier
filigree projects                                # lister les projets et leurs ID
filigree activity ID                             # journal d'activité en JSON
filigree handoff ID                              # reprise en texte (à coller où vous voulez)
filigree mcp-config --client claude|codex|claude-desktop [--command]
filigree hooks install --client claude --inject --dry-run
filigree import-export FICHIER.zip --project ID
```

## Importer l'historique existant (`filigree backfill`)

Filigree ne relit pas le passé tout seul. Pour récupérer aussi les sessions déjà faites : arrêtez l'agent, lancez `filigree backfill --dry-run` pour voir ce qui serait relu, puis `filigree backfill`, et relancez `filigree agent`. L'historique arrive en propositions, avec les mêmes preuves de dossier que le direct ; une session sans dossier prouvé reste en attente. Le relancer ne crée pas de doublons.

## Importer l'historique Codex

Codex 0.16x supprime ses anciens fichiers de session et ne garde l'historique que dans `~/.codex/thread_history_1.sqlite`. Pour récupérer ces fils : `filigree import-codex-history --dry-run` (comptages seulement), puis `filigree import-codex-history`. Le dossier de chaque fil est celui que Codex a enregistré ; un fil dont le dossier n'existe plus, est hors des racines autorisées ou exclu est ignoré et compté avec sa raison. Les fils dont le fichier de session existe encore restent à la capture en direct. Tout arrive en propositions, sans doublon si vous relancez.

## En cas de souci

| Problème | Vérification |
| --- | --- |
| Rien dans **Activité** | Le dossier de la session est-il sous une racine autorisée (`filigree status` → `allowed_roots`) **et** dans un projet ? L'agent tourne-t-il (`filigree status` → `agent`) ? Les sessions antérieures au premier lancement ne sont pas rattrapées. |
| L'agent ne voit pas la mémoire | Pour Claude Code et Codex : `claude mcp list` / `codex mcp list`. Pour Claude Desktop : redémarrez-le complètement et vérifiez `--project-folder` ou `--all-projects`. |
| `python` introuvable dans la configuration MCP | Remplacez `python` par le chemin complet affiché par `filigree mcp-config` (par exemple `C:\Python314\python.exe`). |
| Une session est « en attente » | **Capture → Sessions non rattachées** : choisissez son projet. |

Pour aller plus loin : le [guide complet](README.md), avec les écrans, le fonctionnement, la sécurité et le dépannage détaillé.
