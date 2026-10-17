# Guide d'utilisation de Filigree 0.2

> **Gardez le pourquoi.** Filigree est la mémoire locale de vos projets, partagée par les personnes et leurs agents IA (Claude Code, Codex). Il conserve les décisions, les corrections, les options écartées et leurs sources. Depuis la version 0.2, il observe aussi en continu ce que font vos agents.

Ce guide s'adresse aux développeuses et développeurs qui découvrent Filigree. Comptez **10 minutes** pour l'installer et voir votre première session d'agent apparaître. Les captures d'écran viennent de la vraie interface, alimentée par des données fictives (`node scripts/guide_screenshots.cjs` les régénère). Les schémas sont produits par `python scripts/guide_diagrams.py`.

> **Pressé ?** Le [guide de prise en main](prise-en-main.md) donne directement les commandes pour Claude Code, Claude Desktop, Codex CLI, l'application Codex, claude.ai et ChatGPT.

## Sommaire

1. [Ce que fait Filigree](#1-ce-que-fait-filigree), [comment ça marche](#comment-ça-marche)
2. [Installer](#2-installer)
3. [Démarrer en cinq minutes](#3-démarrer-en-cinq-minutes)
4. [Découvrir l'interface](#4-découvrir-linterface)
5. [Suivre l'activité de vos agents](#5-suivre-lactivité-de-vos-agents)
6. [Connecter vos agents (MCP et hooks)](#6-connecter-vos-agents-mcp-et-hooks)
7. [Lancer Filigree à l'ouverture de session](#7-lancer-filigree-à-louverture-de-session)
8. [Importer vos conversations ChatGPT ou claude.ai](#8-importer-vos-conversations-chatgpt-ou-claudeai)
9. [Référence des commandes](#9-référence-des-commandes)
10. [Où vivent vos données](#10-où-vivent-vos-données)
11. [Confidentialité et sécurité](#11-confidentialité-et-sécurité)
12. [Dépannage](#12-dépannage)
13. [Tout désinstaller](#13-tout-désinstaller)

## 1. Ce que fait Filigree

Votre dépôt Git sait **ce qui** a changé. Filigree garde **pourquoi** : la proposition d'un agent, votre correction, l'option rejetée, la source, et la décision qui a suivi.

- **Une mémoire par dossier.** Un projet Filigree est rattaché à un vrai dossier de votre disque. Les sessions Claude Code ou Codex lancées dans ce dossier alimentent ce projet, et lui seul.
- **Rien n'est décidé à votre place.** Tout ce qui vient d'un agent ou d'un import arrive comme **proposition** (« À examiner »). Vous seul l'acceptez, l'écartez ou la remplacez.
- **Une reprise propre.** Le prochain humain ou le prochain agent reçoit un contexte clair : ce qui est actuel, ce qui reste incertain, et ce qui a été remplacé.
- **Local et portable.** Pas de compte, pas de serveur distant, pas d'appel à un modèle. Les connaissances sont des fichiers Markdown que vous pouvez versionner avec Git.
- **Nouveau en 0.2 :** un **agent local permanent** journalise l'activité de vos sessions (demandes, fichiers modifiés, tests, erreurs, commits). Il propose une **fiche par session** et signale quand deux sessions modifient le même fichier.

### Comment ça marche

![Architecture de Filigree](images/schema-architecture.svg)

1. **Vos applications** (Claude Code, Codex, leurs applications de bureau) écrivent déjà leurs sessions sur votre disque. Filigree ne s'insère pas entre vous et le modèle.
2. **L'agent Filigree** relit ces fichiers en lecture seule, toutes les quelques secondes, et ne garde que les sessions lancées dans un dossier de projet, sous une racine autorisée.
3. Il en tire un **journal d'activité** et des **propositions**, dont une fiche par session.
4. **Vous examinez.** Ce que vous acceptez devient la mémoire actuelle du projet : l'interface, la reprise et le serveur MCP la rendent aux agents suivants.

![Le parcours d'une session](images/schema-session.svg)

![Cycle de vie d'une connaissance](images/schema-revue.svg)

La règle centrale : **rien de ce qui vient d'un agent ne devient une décision sans vous.**

## 2. Installer

**Prérequis :** Python 3.11 ou plus récent. Aucune autre dépendance n'est nécessaire pour utiliser Filigree (Node sert uniquement aux tests de développement).

```sh
git clone https://github.com/TCHINDAJOEL/filigree-memory.git
cd filigree-memory
python -m pip install .
filigree --version          # affiche 0.2.0
```

Choisissez **un dossier de données** et utilisez-le partout (interface, ligne de commande, MCP). Le plus simple est une variable d'environnement :

```sh
# macOS / Linux
export FILIGREE_DATA_DIR=~/FiligreeMemory
# Windows (PowerShell)
$env:FILIGREE_DATA_DIR = "E:\FiligreeMemory"
```

Sans cette variable, Filigree utilise `~/.filigree`. Vous pouvez aussi passer `--data-dir CHEMIN` à chaque commande.

## 3. Démarrer en cinq minutes

**Étape 1 — Dire à Filigree quels dossiers il peut observer.** Seules les sessions lancées sous ces racines seront prises en compte ; les autres restent ignorées, sans qu'aucun contenu ne soit lu.

```sh
filigree setup --root ~/code
```

```json
{
  "allowed_roots": ["/home/vous/code"],
  "next": ["filigree agent  (ou : filigree service install)", "filigree mcp-config --client claude|codex", "filigree hooks install --client claude --dry-run"]
}
```

**Étape 2 — Lancer l'agent Filigree.** Un seul processus fait tout : l'interface web, la capture et le journal d'activité.

```sh
filigree agent
# Filigree agent · http://127.0.0.1:7820
```

Ouvrez **http://127.0.0.1:7820**. L'interface est en français ; vos connaissances peuvent être rédigées dans n'importe quelle langue.

![Écran d'accueil de Filigree](images/01-accueil.png)

*Écran d'accueil. « Explorer la démonstration » crée un projet fictif pour tout essayer sans risque.*

**Étape 3 — Créer votre projet.** Cliquez sur **Créer mon premier projet** (ou sur **+** dans la barre latérale). Indiquez le **chemin absolu d'un dossier existant** : c'est ce dossier qui relie vos sessions d'agent au projet.

![Créer un projet rattaché à un dossier](images/02-creer-projet.png)

*Un projet est un vrai dossier. Les sessions lancées dans ce dossier, ou dans un de ses sous-dossiers, alimentent ce projet.*

Vous pouvez aussi le faire en ligne de commande :

```sh
filigree create "Boutique en ligne" --folder ~/code/boutique
```

**Étape 4 — Travailler normalement.** Ouvrez un terminal dans le dossier du projet et lancez votre agent :

```sh
cd ~/code/boutique
claude          # ou : codex
```

L'activité de la session apparaît dans la vue **Activité** quelques secondes plus tard. Une fiche de session arrive dans **Connaissances** dix minutes après la fin de la session.

## 4. Découvrir l'interface

### Vue d'ensemble

![Vue d'ensemble d'un projet](images/03-vue-ensemble.png)

La vue d'ensemble montre :
- en haut, les compteurs : connaissances, acceptées, à examiner, liens ;
- au centre, les dernières connaissances ;
- à droite, la file **« Un regard humain »** : les propositions qui attendent votre décision.

L'indicateur **Capture active** en haut à droite confirme que l'agent observe vos sessions.

### Connaissances : examiner, accepter, écarter

![Liste des connaissances](images/04-connaissances.png)

Chaque connaissance a :
- un **type** : décision, hypothèse, observation, contrainte, méthode, question ou correction ;
- un **statut** : à examiner, acceptée, écartée ou remplacée ;
- ses **sources**.

La recherche ignore les accents et la casse.

![Détail d'une connaissance](images/05-detail-connaissance.png)

Le panneau de détail affiche :
- **qui l'a déclarée**, par quel **canal** (interface, MCP, capture, import), et sa **révision** ;
- les **sources et preuves**, les **relations** avec d'autres connaissances et l'**historique des révisions**.

Trois actions :
- **Accepter** : la connaissance devient actuelle et figure dans les reprises.
- **Écarter** : elle reste consultable comme alternative historique.
- **Modifier** : chaque modification crée une nouvelle révision, et les précédentes restent lisibles.

> Pour remplacer une décision, créez la nouvelle décision avec la relation **« remplace »**. L'ancienne passe au statut *remplacée* sans être effacée.

### Chronologie et graphe

![Chronologie](images/06-chronologie.png)

La **chronologie** retrace chaque évolution : création, acceptation, remplacement, avec la raison saisie.

![Graphe des relations](images/07-graphe.png)

Le **graphe** montre ce qui *appuie*, *contredit* ou *remplace* une connaissance. Cliquez sur un nœud pour ouvrir ses sources.

### Reprise : transmettre le contexte

![Préparer une reprise](images/08-reprise.png)

La **reprise** produit un texte borné, prêt à copier ou à télécharger, pour un collègue ou un agent. Elle sépare :
- les connaissances **actuelles et acceptées** ;
- les **propositions** encore incertaines ;
- les **alternatives historiques**, marquées explicitement comme « NOT CURRENT ».

Chaque élément garde son identifiant et sa source. Relisez-la avant de l'envoyer à un service externe.

### Capture

![Vue Capture](images/12-capture.png)

La vue **Capture** contrôle l'observation automatique :
- **Désactiver** la capture, la **suspendre**, ou **mettre ce projet en pause** ;
- **exclure un dossier** ;
- **rattacher une session en attente**.

Une session est mise **en attente** dès qu'elle ne peut pas être rattachée sans deviner (dossier ambigu, hors racines, sans projet). Filigree n'en conserve alors que l'identifiant : aucun contenu n'est lu tant que vous ne l'avez pas rattachée vous-même.

### Importer

![Importer des traces](images/13-importer.png)

Collez des notes ou un fichier JSON ou JSONL (exports claude-tap, transcriptions Claude Code ou Codex). Chaque import crée des **propositions**, jamais des décisions.

### Sur mobile

![Vue Activité sur téléphone](images/14-mobile-activite.png)

L'interface s'adapte aux petits écrans, avec la même navigation et les mêmes données.

## 5. Suivre l'activité de vos agents

C'est la grande nouveauté de la 0.2.

![Vue Activité](images/09-activite.png)

La vue **Activité** lit le journal local du projet :

| Élément | Ce qu'il montre |
| --- | --- |
| **Chevauchement possible** | Un même fichier modifié par au moins deux sessions dans les 15 dernières minutes (ici, Claude et Codex sur `cart.py`). |
| **Sessions actives** | Les sessions qui ont travaillé dans les 15 dernières minutes, avec leur client et leur nombre d'événements. |
| **Activité récente** | Demandes, fichiers modifiés, commandes, résultats de tests, erreurs et commits, du plus récent au plus ancien. |

Ce journal est fait d'**indices non revus**. Quelques règles à connaître :

- **Les lignes de commande ne sont jamais conservées.** Seul le nom du programme l'est (`python`, `git`…), car les arguments peuvent contenir des secrets.
- **Les résumés sont expurgés puis tronqués** à 280 caractères. Les jetons, mots de passe et clés connus sont masqués.
- Le raisonnement interne du modèle et les blocs injectés (rappels système) sont exclus.
- **Pas de rattrapage :** au premier lancement, l'agent ne relit pas l'historique de vos anciennes sessions. Seule l'activité nouvelle est journalisée.
- Le journal est conservé **90 jours** (réglable), jamais versionné par Git et jamais exporté.

### Les fiches de session

Après **10 minutes d'inactivité**, ou dès la fin de session si les hooks sont installés, chaque session devient **une proposition** dans *Connaissances* :

![Fiche de session dans les connaissances](images/10-fiche-session.png)

![Contenu d'une fiche de session](images/11-fiche-session-detail.png)

La fiche résume la session : demandes, fichiers modifiés, commandes, tests et erreurs. Elle est générée **sans modèle d'IA**, de façon déterministe.

- Tant qu'elle est *à examiner*, elle est mise à jour si la session reprend.
- Une fois acceptée ou écartée, elle n'est **plus jamais réécrite** : une nouvelle activité crée une proposition « suite ».

> Une commande réussie ne prouve pas que le besoin est satisfait. La fiche décrit ce qui s'est passé ; c'est à vous de juger.

### En ligne de commande

```sh
filigree projects                      # retrouver l'identifiant du projet
filigree activity <ID_PROJET>          # journal récent, sessions actives, chevauchements (JSON)
```

## 6. Connecter vos agents (MCP et hooks)

![Ce que Filigree fait pour chaque application](images/schema-applications.svg)

Les commandes complètes, application par application, sont dans le [guide de prise en main](prise-en-main.md).

### MCP : permettre à l'agent de consulter la mémoire

La capture *écrit* des propositions. Pour qu'un agent puisse **lire** la mémoire, ajoutez une fois le serveur MCP de Filigree à sa configuration. Filigree affiche la commande ou la configuration à copier, sans jamais l'installer lui-même :

```sh
filigree mcp-config --client claude --command     # affiche « claude mcp add --scope user filigree -- … »
filigree mcp-config --client codex --command      # affiche « codex mcp add filigree -- … »
filigree mcp-config --client claude-desktop --project-folder ~/code/boutique   # JSON pour claude_desktop_config.json
```

Sans `--command`, la configuration est affichée sous forme de bloc (JSON pour Claude, TOML pour Codex) :

```json
{
  "mcpServers": {
    "filigree": {
      "command": "python",
      "args": ["-m", "filigree", "--data-dir", "/home/vous/FiligreeMemory", "mcp"]
    }
  }
}
```

Outils proposés aux agents :

| Outil | Rôle |
| --- | --- |
| `list_projects`, `project_for_folder` | Trouver le projet du dossier courant |
| `search_memory`, `get_handoff` | Chercher, obtenir une reprise (option `accepted_only`) |
| `project_activity`, `active_sessions` | Lire le journal d'activité et les chevauchements (données non revues) |
| `propose_memory` | Proposer une connaissance, que vous examinerez |

Aucun outil ne permet à un agent d'**accepter** quoi que ce soit.

Depuis la version 0.2, le serveur MCP ne voit **que le projet du dossier où l'agent travaille**. Il l'apprend par les *roots* MCP : le client lui communique ses dossiers de travail. C'est vérifié en réel avec Claude Code, qui ne lance pas le serveur depuis le dossier du projet. Si un client ne fournit pas de roots, le serveur se rabat sur son dossier de lancement. Deux options rendent le périmètre explicite :
- `--project-folder DOSSIER` désigne un projet précis, ce qui est obligatoire pour Claude Desktop ;
- `--all-projects` les ouvre tous, explicitement.

Si un agent répond « Project outside this MCP server's scope », ajoutez l'une de ces deux options dans sa configuration.

### Hooks : signaux de session et contexte au démarrage (optionnel)

Les hooks prolongent l'observation. Ils sont **facultatifs** et doivent être installés **explicitement**. Commencez toujours par regarder ce qui changerait :

```sh
filigree hooks install --client claude --inject --dry-run
```

```diff
+{
+  "hooks": {
+    "SessionStart": [{ "hooks": [{ "type": "command",
+        "command": "\"python\" \"-m\" \"filigree\" \"--data-dir\" \"…\" \"signal\" \"--client\" \"claude\" \"--event\" \"session_start\" \"--inject\"",
+        "timeout": 10 }] }],
+    "SessionEnd":   [{ "hooks": [{ "type": "command",
+        "command": "\"python\" \"-m\" \"filigree\" … \"signal\" \"--client\" \"claude\" \"--event\" \"session_end\"",
+        "timeout": 10 }] }]
+  }
+}
```

Si le diff vous convient, relancez la commande sans `--dry-run`. Ce que fait l'installation :

- **Sauvegarde :** une copie horodatée du fichier est faite avant toute écriture (`settings.json.filigree-backup-…`), et chaque action est notée dans `.runtime/install-log.jsonl`.
- **Fin de session :** le signal déclenche immédiatement la fiche de session.
- **Avec `--inject` :** au démarrage d'une session Claude Code, les connaissances **acceptées** du projet (et elles seules) sont ajoutées au contexte de l'agent.
- **Sécurité du hook :** il ne transmet que l'identifiant de session, s'exécute en moins d'une seconde et ne fait jamais échouer votre agent.
- **Garde-fous :** Filigree refuse de modifier un `settings.json` invalide, ou un `config.toml` de Codex qui définit déjà un `notify`.

```sh
filigree hooks status                       # où en sont les hooks
filigree hooks uninstall --client claude    # retrait propre, avec sauvegarde
```

> Filigree ne modifie jamais `CLAUDE.md` ni `AGENTS.md`.

## 7. Lancer Filigree à l'ouverture de session

Pour ne plus avoir à lancer `filigree agent` à la main :

```sh
filigree service install --dry-run   # affiche ce qui serait installé
filigree service install
filigree service status
filigree service uninstall
```

| Système | Ce qui est installé (sans droits administrateur) |
| --- | --- |
| Windows | Une valeur « Filigree Agent » sous `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (lancement avec `pythonw`, sans fenêtre) |
| macOS | `~/Library/LaunchAgents/dev.filigree.agent.plist`, relancé seulement en cas d'échec |
| Linux | `~/.config/systemd/user/filigree-agent.service` (`systemctl --user`) |

Un seul agent tourne par dossier de données. Si vous lancez `filigree serve` alors qu'un agent tourne déjà, Filigree vous renvoie simplement vers son adresse.

## 8. Importer vos conversations ChatGPT ou claude.ai

Exportez vos données depuis ChatGPT (*Paramètres → Contrôles des données → Exporter*) ou depuis claude.ai (*Settings → Privacy → Export data*). Vous recevez une archive `.zip` qui contient `conversations.json`.

```sh
filigree import-export ~/Téléchargements/export.zip --project <ID_PROJET>
```

```json
{ "format": "chatgpt", "conversations": 42, "messages": 610, "imported": 610, "duplicates": 0 }
```

- Le **projet cible est toujours explicite** : Filigree ne devine jamais à quel projet appartient une conversation.
- Pour ChatGPT, seule la branche de conversation que vous avez vue en dernier est importée.
- Les messages système, les sorties d'outils et les messages masqués sont ignorés.
- Les secrets reconnus sont masqués, et chaque message devient une **proposition**.
- Réimporter la même archive ne crée pas de doublon.

## 9. Référence des commandes

| Commande | Rôle |
| --- | --- |
| `filigree agent [--port N]` | Agent permanent : interface, capture, journal d'activité, fiches de session |
| `filigree serve [--no-capture]` | Interface seule, comme en 0.1 (laisse la main à un agent déjà lancé) |
| `filigree setup --root DOSSIER` · `--any-folder` | Racines observables ; `--any-folder` lève la restriction |
| `filigree create NOM --folder DOSSIER` | Créer un projet rattaché à un dossier |
| `filigree attach ID DOSSIER` | Rattacher un dossier à un ancien projet sans dossier |
| `filigree projects` | Lister les projets et leurs identifiants |
| `filigree activity ID` | Journal d'activité d'un projet (JSON) |
| `filigree handoff ID [--query …]` | Reprise en texte sur la sortie standard |
| `filigree export ID` | Export Markdown lisible |
| `filigree import ID FICHIER` · `watch ID FICHIER` | Importer, ou surveiller, un fichier de traces |
| `filigree import-export FICHIER --project ID` | Import ChatGPT ou claude.ai |
| `filigree mcp [--project-folder D \| --all-projects]` | Serveur MCP sur stdio |
| `filigree mcp-config --client claude\|codex\|claude-desktop [--command] [--project-folder D \| --all-projects]` | Afficher la commande ou la configuration MCP à installer vous-même |
| `filigree hooks install\|uninstall\|status --client …` | Hooks optionnels |
| `filigree service install\|uninstall\|status` | Démarrage automatique optionnel |
| `filigree capture status\|pending\|link\|pause\|resume\|exclude…` | Piloter la capture fine |
| `filigree probe` | Sources d'agents lisibles sur ce poste (comptages seulement) |
| `filigree status` | Tout ce que Filigree a installé ou fait tourner, et ses fichiers (JSON) |

## 10. Où vivent vos données

```text
<dossier de données>/
  projects/<id>/
    project.json                 # nom, intention, dossier rattaché
    .filigree/
      entries/<id>.md            # chaque connaissance : Markdown + bloc de métadonnées
      history/<id>/<rév>.md      # révisions précédentes
      events/<id>.json           # journal des changements
      activity.sqlite            # journal d'activité 0.2 (hors Git, hors export)
  .capture/                      # réglages (capture.json) et état de la capture
  .runtime/                      # agent.key, agent.json, signaux, journal d'installation
```

- **Sauvegarder :** copiez le dossier de données. Aucune base n'est à reconstruire, il suffit de relancer Filigree sur la copie.
- **Versionner :** le bouton **Git ↗** crée des points de sauvegarde dans un dépôt dédié à la mémoire, séparé de votre code. Le journal d'activité n'y entre jamais.
- **Régler la conservation :** dans `.capture/capture.json`, la section `"activity": {"enabled": true, "retention_days": 90, "turn_proposals": true}`. Mettez `turn_proposals` à `false` pour ne garder que le journal et les fiches de session, sans proposition à chaque échange.

## 11. Confidentialité et sécurité

- **Tout reste sur votre machine.** L'interface n'écoute que sur `127.0.0.1`, et il n'y a ni télémétrie ni appel à un modèle.
- **Toutes les routes de l'API exigent une clé locale** (`.runtime/agent.key`). Cette clé protège des sites web malveillants, pas des programmes qui tournent sous votre propre compte.
- **L'agent lit vos transcriptions en lecture seule.** Il ne retient que les sessions des dossiers autorisés qui appartiennent à un projet.
- **Le masquage des secrets est heuristique.** Relisez avant de publier ou de partager une reprise.
- **« Acceptée » signifie « acceptée dans l'interface locale ».** Ce n'est pas une preuve d'identité. Avec `--inject`, les connaissances acceptées sont lues par vos agents : acceptez-les avec le même soin qu'une revue de code.

Le détail figure dans [SECURITY.md](../../SECURITY.md).

## 12. Dépannage

| Symptôme | Que faire |
| --- | --- |
| La vue Activité reste vide | Vérifiez que l'agent tourne (`filigree status` → `agent`), que la session a été lancée **dans** le dossier du projet, et que ce dossier est sous une racine autorisée (`allowed_roots`). Rappel : l'historique antérieur au premier lancement n'est pas rattrapé. |
| « Capture désactivée » | Le serveur a été lancé avec `--no-capture`, ou `capture.json` contient une valeur invalide : `filigree capture status` affiche `settings_error`. |
| Une session reste « en attente » | Ouvrez **Capture → Sessions non rattachées** et choisissez son projet, ou lancez `filigree capture link CLÉ ID_PROJET`. Une session hors racines y apparaît avec le motif `outside_roots`. |
| Erreur 403 dans un script qui lit l'API | Depuis la 0.2, chaque appel doit envoyer l'en-tête `X-Filigree-Token`. Récupérez la clé via `GET /api/bootstrap`. |
| L'agent MCP ne voit pas mon projet (« outside this MCP server's scope ») | Le client n'a pas communiqué ses dossiers de travail (roots), ou le dossier n'appartient à aucun projet. Ajoutez `--project-folder DOSSIER` (ou `--all-projects`) dans sa configuration, ou régénérez-la avec `filigree mcp-config … --project-folder DOSSIER`. |
| « Un agent Filigree tourne déjà » | C'est normal : un seul agent par dossier de données. `filigree status` donne son adresse. |
| « Clé locale illisible ou corrompue » | Arrêtez Filigree, supprimez `.runtime/agent.key`, puis relancez : une nouvelle clé est créée. |
| Codex : anciennes sessions absentes | Les journaux compressés `.zst` ne sont pas lus, et les sessions actives (non compressées) le sont. `filigree probe` indique ce qui est lisible. |

## 13. Tout désinstaller

```sh
filigree hooks uninstall --client claude
filigree hooks uninstall --client codex
filigree service uninstall
filigree status                  # vérifier qu'il ne reste rien d'installé
python -m pip uninstall filigree-memory
```

Vos connaissances restent dans le dossier de données : supprimez-le seulement si vous n'en avez plus besoin.

---

*Guide rédigé pour Filigree 0.2.0. Les captures montrent des données fictives. Signalez une erreur ou une imprécision dans les [issues GitHub](https://github.com/TCHINDAJOEL/filigree-memory/issues).*
