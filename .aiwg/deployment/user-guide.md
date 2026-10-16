# Filigree — utilisation et démonstration

## Démarrer

Prérequis : Python 3.11 ou plus récent. Git est facultatif ; GitHub CLI n'est pas nécessaire pour consulter ou modifier la mémoire.

Depuis le dossier du logiciel :

```powershell
python -m filigree --data-dir .filigree-data serve
```

Ouvrir http://127.0.0.1:7820. Le processus doit rester actif ; Ctrl+C l'arrête. Le dossier `.filigree-data` est ignoré par le dépôt du logiciel. Pour conserver votre mémoire ailleurs, utilisez un chemin absolu avec `--data-dir`. Le même chemin est requis dans tous les clients.

Le bouton « Explorer la démonstration » crée un projet entièrement fictif. Votre vraie conversation n'est pas publiée avec le logiciel.

## Parcours quotidien

Créer un projet en indiquant un dossier local existant (chemin absolu) et son intention. Un projet créé avec une version antérieure s'affiche « sans dossier » : utiliser « Rattacher un dossier » dans la vue d'ensemble. Ajouter une connaissance ou importer une note/export. Les imports restent proposés : l'application n'invente pas un statut de décision à partir du texte. Le type, les sources, le libellé d'épisode et les relations peuvent ensuite être enrichis dans la fiche.

Accepter signifie retenir une connaissance ; ce n'est pas une preuve de vérité. Écarter la conserve dans l'histoire. Remplacer crée une nouvelle connaissance acceptée, reliée à la précédente : l'ancienne devient non actuelle. Une justification facultative accompagne les changements de statut ou révisions. Les anciennes versions sont consultables dans la fiche.

Le graphe montre des liens enregistrés : appuie, contredit, remplace, est lié à, met en œuvre. Il n'infère pas des causalités. La recherche porte sur le texte ; elle ne comprend pas les synonymes comme un moteur sémantique.

La reprise fournit objectif, connaissances actuelles, incertitudes et alternatives historiques marquées `NOT CURRENT`. Le budget est exprimé en caractères, pas en tokens. Les éléments trop longs peuvent être omis : consulter les références et la mémoire complète si le contexte ne suffit pas.

## Import et confidentialité

Formats utilisables : texte/Markdown (une observation par note), événements JSON normalisés, messages visibles JSONL Claude/Codex, JSONL brut et JSON complet claude-tap. Exemples synthétiques dans `examples/`. Ne pas importer le bundle compact par défaut ; exporter depuis claude-tap avec `--format json`.

La surveillance CLI porte uniquement sur le fichier choisi. Elle n'intercepte pas Claude ou Codex elle-même. Le lanceur `claude-tap` est un outil externe. Les explications exprimées sont utilisables ; les blocs de pensée interne ne sont pas une source à récupérer.

Les corps et extraits sélectionnés sont enregistrés dans la mémoire ; les originaux restent dans leur emplacement initial. Des clés et mots de passe reconnaissables sont masqués, sans garantie exhaustive. Les anciennes révisions peuvent toujours contenir une information que vous corrigez plus tard. Examiner avant de publier.

## Capture automatique des sessions d'agents

**Principe.** Un projet correspond à un vrai dossier. Quand `filigree serve` tourne, un moniteur propose des connaissances sourcées à partir de deux sources : la base SQLite de claude-tap, lue en **lecture seule** (schéma 4 uniquement), et, pour un client lancé **directement** (simple commande `claude` ou `codex`, sans claude-tap), les transcriptions locales que ce client écrit. Il retient le texte visible (vous et l'agent), les appels d'outils et leurs résultats bornés (commandes, erreurs, validations) et, côté claude-tap, les échecs HTTP (code et court extrait). Il ignore la pensée interne (blocs de pensée, messages Codex du canal `analysis` et variantes de raisonnement interne, dans les deux sources), les consignes système ou développeur et les blocs injectés. Seul le tour nouveau de chaque échange est retenu. Tout arrive à l'état « À examiner » ; aucun modèle n'est appelé et aucune décision n'est déduite.

**Comment le dossier est trouvé.** claude-tap n'enregistre pas de dossier de travail. Filigree lit l'identifiant de session annoncé par la trace, puis cherche **ce même identifiant** dans les transcriptions locales de Claude Code ou de Codex (seulement `sessionId`/`id` et `cwd`). Si un seul dossier valide en résulte, la session va au projet enregistré pour ce dossier ou son plus proche ancêtre ; à défaut, un projet est créé pour la racine Git la plus proche (sinon le dossier lui-même). Claude et Codex lancés dans le même dossier alimentent donc le même projet. Codex annonce `session_id` et `thread_id` : les deux sont lus et toute divergence est un conflit. Si l'identité est inconnue, contradictoire ou ambiguë, rien n'est deviné : la session reste **en attente** (clés seulement, sans contenu) dans la vue « Capture », où vous choisissez le projet, ou avec `filigree capture link CLÉ ID_PROJET`. Votre choix explicite pour une session `tap:ID` contradictoire est respecté ; les entrées indiquent `link: explicit`, les identifiants annoncés et le dossier **que vous avez choisi** (`target_folder`), en précisant que ce n'est pas une preuve issue d'une transcription native. Deux rattachements explicites qui se contredisent laissent la session en attente (`mapping_conflict`).

**Lancement direct, sans claude-tap (repli natif, activé par défaut).** Une transcription native nomme sa session et son dossier : le moniteur lit les nouvelles lignes complètes et les classe dans le projet du dossier (créé au premier usage). Comptez un délai de quelques secondes jusqu'à environ une minute : un court délai laisse claude-tap enregistrer d'abord le même échange, et un fichier écrit en continu est lu quand même après une attente maximale. Passer de claude-tap au lancement direct, ou l'inverse, ne duplique pas les messages : chaque canal garde un registre borné et expirant (15 min) d'empreintes de contenu par session native et ignore ce que l'autre a déjà classé. Un message identique envoyé plus tard, ou après la fenêtre, est une nouvelle activité : une session qui a utilisé claude-tap n'est jamais réduite au silence. Désactivation : `filigree capture fallback off`. Le défaut ne s'applique que si `capture.json` ne mentionne pas ce réglage : une installation où un réglage a déjà été modifié contient `"native_fallback": false` (écrit par les versions antérieures) et reste désactivée jusqu'à `filigree capture fallback on`.

**Démarrage et arrêt.** Le moniteur doit tourner pour capturer : `filigree serve` le démarre (`--no-capture` pour l'éviter ; à utiliser pour tout serveur de test ou de paquet), ou `filigree capture start --background` / `filigree capture run`. `filigree capture stop` demande un arrêt coopératif ; aucun processus n'est tué. Pour lancer le moniteur à chaque ouverture de session Windows, vous pouvez **optionnellement** exécuter `scripts/install-capture-startup.ps1 -DataDir CHEMIN` (raccourci utilisateur, sans droits d'administrateur, confirmation demandée) ; `scripts/uninstall-capture-startup.ps1` le retire. Rien n'est installé sans votre accord.

**Seulement l'avenir.** Au premier scan, les sessions claude-tap et les transcriptions existantes forment une ligne de base et ne sont pas importées. Une pause, une désactivation ou un dossier exclu ne sont pas rattrapés. L'historique d'une session rattachée à la main n'est importé que sur demande (`--import-history`).

**Contrôles.** La vue « Capture » et la commande `filigree capture` permettent de suspendre, reprendre, désactiver, exclure un dossier, mettre un projet en pause et rattacher les sessions en attente. La démonstration utilise son propre dossier vide et n'est jamais alimentée.

**Pour que les agents relisent la mémoire.** Exécuter `filigree mcp-config --client claude` ou `--client codex` : la commande **affiche** la configuration MCP, vous l'installez une seule fois vous-même. Filigree ne modifie jamais la configuration d'un agent, `CLAUDE.md` ni `AGENTS.md`. L'outil `project_for_folder` retrouve le projet d'un dossier ; il ne crée rien.

**Limites réelles.** Aucune interception magique : claude-tap n'enregistre que les clients lancés par lui ; un lancement direct dépend du repli natif et d'une transcription locale de Claude Code ou de Codex. Le repli natif Claude Code a été vérifié par un lancement réel sur un projet synthétique ; Codex reste couvert par des transcriptions synthétiques seulement (les formats réels peuvent évoluer) ; une session dont le dossier ne peut pas être établi y est **retenue** : le décalage dans la transcription reste à la ligne concernée, la session apparaît en attente (clé et motif, sans texte ; le contenu reste dans la transcription de l'agent) et la lecture reprend à cet endroit, dans l'ordre, dès que la session se résout ou que vous la rattachez avec `filigree capture link ID_SESSION ID_PROJET`. Seules une pause ou une exclusion délibérées sont ignorées définitivement. Au plus 100 fichiers sont retenus ; au-delà, la perte est comptée et signalée. Une réécriture de transcription vers une taille **plus grande** dans la partie déjà lue n'est pas détectée ; une réécriture de même taille l'est (date de modification) et abandonne l'ancienne correspondance de dossier. La déduplication entre canaux porte sur le texte visible exact (15 min) : au pire un doublon proposé, jamais une perte. Si le chemin de la base claude-tap change, les clés en attente de l'ancienne base sont mises de côté dans `pending.quarantine-*.json` (clés seulement) au lieu d'être rejouées ; un rattachement `tap:ID` est enregistré avec l'identité de la base pour laquelle il a été choisi et ne s'applique qu'à elle (les autres sont comptés dans `capture status`, champ `mappings_other_database`) ; un rattachement par identifiant natif ne dépend pas de la base. L'onglet de conversation de Claude Desktop et Claude sur le web ne sont pas couverts. Les identifiants lus sont des déclarations locales, pas une authentification. Les résultats d'outils peuvent contenir des informations sensibles ; le masquage est heuristique, relisez avant d'accepter ou de publier. Une session réécrite ou supprimée dans claude-tap est signalée, sans modifier la mémoire. Un schéma claude-tap autre que 4, une base absente, verrouillée ou illisible sont indiqués dans la vue « Capture » et rien n'est lu.
## Git et retour après clonage

Le bouton Git initialise un dépôt **dans le dossier du projet mémoire**, pas dans le code du projet suivi. Créer un point de sauvegarde prend un état des fichiers mémoire. Un index contenant des fichiers étrangers est refusé. Les écritures de l'application et le checkpoint utilisent le même verrou local.

Pour connecter GitHub, utiliser le dossier mémoire `DATA_DIR/projects/PROJECT_ID` et un dépôt privé :

```powershell
gh auth login
gh repo create NOM_DU_DEPOT --private --source "DATA_DIR/projects/PROJECT_ID" --remote origin
```

Le bouton « Pousser vers le distant » apparaît ensuite. Aucun push forcé, achat de crédit ou synchronisation silencieuse n'est effectué. Git doit connaître votre identité (`git config user.name` et `git config user.email`). Un échec réseau n'efface pas la mémoire locale.

Pour reprendre sur une autre machine, cloner dans `NOUVEAU_DATA_DIR/projects/PROJECT_ID`, en conservant l'identifiant de `project.json`, puis lancer Filigree sur `NOUVEAU_DATA_DIR`. Les sources sélectionnées et révisions suivent le clone. Les originaux privés externes ne suivent pas. Le test de portabilité utilise réellement un clone Git local.

Les fichiers Markdown peuvent se lire sans l'application. Si vous les modifiez manuellement, arrêter les processus d'écriture et conserver le bloc de métadonnées et le titre cohérents. Ces modifications manuelles ne créent pas de révision d'audit automatiquement ; Git reste votre historique externe. Préférer l'interface pour préserver l'audit applicatif.

## Démonstration de cinq minutes

1. Créer la démonstration. Présenter l'objectif humain et agent.
2. Ouvrir « Utiliser Basic Memory comme socle » : c'est une proposition, avec source fictive affichée.
3. Ouvrir le recadrage : « Définir la méthode avant les outils ». Montrer sa contradiction explicite avec la proposition.
4. Ajouter ou remplacer une connaissance, puis ouvrir sa chronologie et ses anciennes versions.
5. Afficher le graphe et la fiche de reprise. Le choix technique reste ouvert ; aucune « validation de Basic Memory » n'est inventée.
6. Exporter le Markdown et montrer le fichier canonique. Expliquer que MCP lit les mêmes données.
7. Présenter les tests réellement exécutés et les limites du périmètre.

## Défendre les choix

**Pourquoi pas une base graphe ?** Les relations utiles existent déjà dans les fichiers ; un index supplémentaire n'est justifié que par des limites mesurées.

**Pourquoi pas une synthèse automatique dès le départ ?** La fidélité des statuts et des sources doit être démontrée avant d'automatiser leur interprétation. Un agent peut déjà proposer une synthèse sourcée via MCP ; l'humain la révise.

**Pourquoi Python et du JavaScript simple ?** Une application locale installable sans pile de services ni build du frontend, inspectable par un contributeur. Ce choix a des limites de recherche, volumétrie et déploiement publiquement assumées.

**Quelle originalité ?** Le protocole de continuité : conserver la compréhension corrigée et les alternatives, distinguer proposition et acceptation, et rendre la même mémoire lisible par un humain et consultable par un agent.

**Qu'est-ce qui est prouvé ?** Les comportements dans le rapport de vérification. Ni l'économie de tokens ni la productivité ni la compréhension de tous les modèles ne sont revendiquées sans mesure.
