> Brouillon initial, remplacé par `livrables/Guide_utilisation_Filigree.docx` (texte : `guide-utilisation-final.md`).

# Atelier Filigree : garder le pourquoi d'un projet

Ce guide s'adresse à un chef de projet qui n'est pas expert. Il propose trois exercices fictifs, des prompts à copier et un tableau de recette à remplir pendant l'atelier. **Les scénarios sont préparés, pas exécutés** : aucun résultat n'est annoncé ici. Chaque ligne de la recette reste vide tant que vous ne l'avez pas observée vous-même.

## 1. Ce que Filigree fait, et ne fait pas

- Filigree **conserve et partage** une mémoire de projet : propositions, corrections, alternatives écartées, sources, décisions.
- Filigree **ne lance aucun agent**. Vous ouvrez vous-même chaque session (Claude Code, Codex ou autre) et vous collez le prompt du rôle.
- Les rôles (chef de projet, architecte, développeur, testeur) sont **déclaratifs** : un nom écrit dans un champ, pas une identité authentifiée. Ne vous en servez pas comme preuve de qui a fait quoi.
- Aucun fichier de configuration d'agent n'est modifié par Filigree (ni `CLAUDE.md`, ni `AGENTS.md`).

## 2. Vocabulaire à connaître

- **États** : *proposé* (suggéré, rien n'est retenu), *accepté* (vous l'avez retenu ; ce n'est pas une preuve de vérité), *écarté* (refusé, gardé dans l'histoire), *remplacé* (une connaissance acceptée plus récente prend la place ; l'ancienne n'est plus actuelle).
- **Type** : la nature de la connaissance (par exemple décision, contrainte, risque, question). Vous le choisissez dans la fiche.
- **Épisode** : un libellé qui regroupe des notes d'un même sujet (par exemple « cadrage »). Ce n'est pas une tâche suivie automatiquement.
- **Source** : l'extrait ou la référence qui justifie la connaissance. Une connaissance sans source est plus difficile à défendre.
- **Relations** : liens enregistrés explicitement (appuie, contredit, remplace, est lié à, met en œuvre). Le **graphe** n'affiche que ces liens : il n'invente aucune causalité.
- **Proposition MCP ≠ acceptation** : un agent peut chercher, lire une reprise et *proposer* via MCP. Il ne peut pas accepter. L'acceptation se fait uniquement dans l'interface, par vous.
- **Fiche de reprise** : objectif, connaissances actuelles, incertitudes, alternatives historiques marquées `NOT CURRENT`. Son **budget se compte en caractères**, pas en tokens ; un élément trop long peut être omis, il faut alors suivre les références.
- **Recherche** : lexicale. Elle trouve les mots écrits, pas les synonymes. Cherchez avec les termes du texte.

## 3. Préparation (environ 5 minutes)

Deux dossiers **distincts** : le code fictif et la mémoire. La mémoire ne va jamais dans le dossier du code. Les chemins doivent être absolus et les dossiers de code doivent exister avant de créer les projets.

```powershell
New-Item -ItemType Directory -Force E:\Atelier\memoire | Out-Null
New-Item -ItemType Directory -Force E:\Atelier\code\atlas-boutique | Out-Null
New-Item -ItemType Directory -Force E:\Atelier\code\agora-association | Out-Null
New-Item -ItemType Directory -Force E:\Atelier\code\orion-stock | Out-Null
```

Lancez l'interface **sans capture** et laissez cette fenêtre ouverte (Ctrl+C l'arrête) :

```powershell
python -m filigree --data-dir E:\Atelier\memoire serve --no-capture
```

Ouvrez http://127.0.0.1:7820 et créez un projet par dossier, avec une intention d'une phrase. Gardez **le même `--data-dir`** pour tous les outils : un autre chemin ouvre une autre mémoire, vide.

Pour que les agents relisent la mémoire, affichez le snippet MCP (il n'est qu'**affiché** ; vous l'installez vous-même, une fois, dans votre client) :

```powershell
python -m filigree --data-dir E:\Atelier\memoire mcp-config --client claude
```

Sans cette configuration MCP, un agent ne peut pas relire la mémoire. Démarrez chaque agent dans le dossier de code du projet concerné, par exemple `E:\Atelier\code\atlas-boutique`.

## 4. Les trois projets fictifs

| Projet | Sujet | Point d'attention |
|---|---|---|
| **Atlas Boutique** | Vitrine avec commande et retrait en magasin, **sans paiement en ligne** | L'architecte sera tenté d'ajouter un paiement : le chef refuse. |
| **Agora Association** | Inscriptions à un atelier, **capacité 24 personnes**, **données minimales** | Le testeur conteste le traitement de la 25e personne et les données collectées. |
| **Orion Stock** | Outil **hors ligne** (SQLite), **import CSV**, puis **changement de décision** | Le chef remplace une décision ; le nouvel agent doit voir l'ancienne alternative comme non actuelle. |

Les trois projets sont indépendants : ne mélangez ni leurs notes ni leurs dossiers.

## 5. Le déroulé, rôle par rôle

Budget cible : **8 minutes par projet** (lecture des prompts comprise). Pour chaque rôle, ouvrez une session, collez le prompt, puis faites **vous-même** le contrôle indiqué dans l'interface. Remplacez `<PROJET>` par Atlas Boutique, Agora Association ou Orion Stock, et `<CONTRAINTE>` par la ligne du tableau de la section 4.

**Chef de projet (cadre).**
```text
Rôle déclaré : chef de projet. Projet : <PROJET>. Contrainte : <CONTRAINTE>.
Relis d'abord la mémoire du projet (get_handoff). Puis propose via MCP (propose_memory)
trois éléments : l'objectif, les contraintes, les questions ouvertes. Cite une source pour chacun.
N'invente aucune décision.
```
*Contrôle* : dans « Connaissances », les éléments sont **proposés**. Acceptez l'objectif et les contraintes (avec une justification courte), laissez les questions ouvertes.

**Architecte (propose).**
```text
Rôle déclaré : architecte. Projet : <PROJET>.
Relis la mémoire, puis propose une option technique avec ses avantages et ses limites,
et une alternative écartée avec la raison. Ne présente rien comme décidé.
```
*Contrôle* : l'option est en *proposé*. Ajoutez le type et l'épisode dans la fiche. Créez une relation « appuie » ou « contredit » vers la contrainte concernée, puis ouvrez le graphe.

**Développeur (prépare un plan).**
```text
Rôle déclaré : développeur. Projet : <PROJET>.
Relis la mémoire. Ne considère comme acquis que ce qui est accepté. Propose un plan en étapes
qui indique, pour chaque étape, la connaissance acceptée sur laquelle elle s'appuie.
```
*Contrôle* : le plan arrive en *proposé* ; vérifiez qu'il ne s'appuie pas sur une option non acceptée.

**Testeur (conteste).**
```text
Rôle déclaré : testeur. Projet : <PROJET>.
Relis la mémoire et le plan. Propose une objection précise : un cas limite, une donnée en trop
ou une contrainte non respectée. Indique ce qui prouverait que l'objection est levée.
```
*Contrôle* : l'objection est reliée par « contredit » à ce qu'elle conteste.

**Chef de projet (accepte ou refuse).** Travail dans l'interface, sans agent.
- Atlas : refusez (*écarter*) la proposition de paiement en ligne, avec une justification.
- Agora : acceptez l'objection du testeur (liste d'attente au-delà de 24, champs réduits).
- Orion : acceptez « import CSV vers SQLite », puis **remplacez** cette décision par la nouvelle ; l'ancienne devient non actuelle.

**Nouvel agent (reprend).** Ouvrez une session neuve dans le même dossier de code.
```text
Rôle déclaré : nouvel agent. Projet : <PROJET>.
Sans rien supposer, récupère la reprise (get_handoff). Dis-moi : 1) la décision actuelle,
2) l'ancienne alternative et pourquoi elle n'est plus actuelle, 3) ce qui reste incertain,
4) les références de tes sources.
```
*Contrôle* : la réponse distingue la décision actuelle de l'ancienne alternative, et ne présente aucune proposition comme acceptée.

## 6. Tableau de recette observable

À remplir pendant l'atelier. Une case vide signifie « non observé ».

| Étape | À observer dans l'interface | Observé (oui/non) | Remarque |
|---|---|---|---|
| Cadrage | Objectif et contraintes en *proposé*, puis *accepté* après votre action | | |
| Proposition de l'architecte | Option en *proposé*, source visible | | |
| Plan du développeur | Plan en *proposé*, lié aux connaissances acceptées | | |
| Objection du testeur | Relation « contredit » visible dans le graphe | | |
| Décision du chef | État *écarté* ou *accepté* avec justification | | |
| Remplacement (Orion) | Ancienne décision non actuelle, historique consultable | | |
| Reprise du nouvel agent | Décision actuelle et ancienne alternative séparées | | |

## 7. Checklist de 15 cas

Cochez au fur et à mesure ; n'écrivez « fait » que pour ce que vous avez réellement vu.

1. Le dossier de code existe et son chemin est absolu.
2. Le dossier mémoire est distinct du dossier de code.
3. Le serveur tourne avec `--no-capture` et la page s'ouvre.
4. Les trois projets sont créés, chacun lié à son propre dossier.
5. Le snippet MCP a été affiché (pas installé automatiquement) et installé par vous.
6. Une proposition d'agent arrive en *proposé*, jamais en *accepté*.
7. Aucun agent ne peut accepter : l'acceptation n'existe que dans l'interface.
8. Une connaissance a un type, un épisode et une source.
9. Une relation « contredit » apparaît dans le graphe, et aucune relation non saisie n'apparaît.
10. La recherche trouve un mot exact du texte et ne trouve pas un synonyme.
11. Atlas : le paiement en ligne est *écarté* avec sa justification.
12. Agora : la limite de 24 personnes et les données minimales sont acceptées.
13. Orion : la décision remplacée est marquée non actuelle mais reste consultable.
14. La reprise respecte le budget en caractères ; en cas d'omission, les références permettent de retrouver le texte.
15. Le nouvel agent restitue la décision actuelle et l'ancienne alternative sans les confondre.

## 8. Dépannage

- **Rien n'apparaît** : vérifiez que le serveur et l'agent utilisent exactement le même `--data-dir`.
- **Création de projet refusée** : le dossier doit exister, avec un chemin absolu.
- **Un agent ne retrouve pas la mémoire** : le MCP n'est pas installé, ou pointe vers un autre dossier mémoire. Le dossier mémoire n'est pas le dossier du code.
- **Rien ne se capture** : normal avec `--no-capture` ; l'atelier n'en a pas besoin, car les propositions viennent de MCP.
- **Capture activée, rien n'arrive** : le moniteur doit tourner. La capture ne retient que le **futur** (une ligne de base ignore ce qui existe déjà).
- **Sessions « en attente »** : Filigree ne devine jamais le dossier. Rattachez-les dans la vue « Capture » ou avec `filigree capture link CLÉ ID_PROJET`.
- **Codex** : seulement couvert par des fixtures synthétiques, pas par un test réel ; traitez-le comme non vérifié.

## 9. Attention : capture et vrai projet

Pendant l'atelier, la capture reste **désactivée** (`--no-capture`) et les racines sont synthétiques. Activée, la capture peut lire les sources locales (transcriptions de vos agents), donc potentiellement des conversations sans rapport avec l'atelier.

Pour l'activer sur **votre vrai projet**, après l'atelier, en connaissance de cause : créez le projet avec le vrai dossier, puis lancez le serveur sans `--no-capture` (ou `capture start --background`).

```powershell
python -m filigree --data-dir E:\MesMemoires serve
python -m filigree --data-dir E:\MesMemoires capture status
```

Les contenus capturés arrivent comme propositions à relire ; le masquage des secrets est heuristique et non garanti. Relisez avant d'accepter ou de publier.

## 10. Ce que ce guide ne prouve pas

Les prompts et le tableau décrivent ce que vous devriez pouvoir observer ; ils ne constituent pas un résultat de test. Aucune exécution avec deux agents réels n'est affirmée ici : si elle réussit, elle sera consignée à part, avec sa preuve.
