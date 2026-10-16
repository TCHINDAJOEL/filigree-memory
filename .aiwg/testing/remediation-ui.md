# Remédiation interface — D-1 à D-7 et P3 (agent UI)

Date : 16 octobre 2026. Périmètre : `filigree/static/app.js`, `styles.css`, `index.html` (inchangé), `tests/browser/remediation.spec.cjs`. **Ce rapport ne déclare aucune version prête à publier** ; l'intégration et la vérification indépendante restent à faire.

## Exécution

| Commande | Résultat |
| --- | --- |
| `node --check filigree/static/app.js` | code 0 |
| Playwright CLI local (Chromium réel) sur `remediation.spec.cjs`, lancé par un petit `node -e` qui isole `HOME`/`USERPROFILE`/`CLAUDE_CONFIG_DIR`/`CODEX_HOME` | **16 réussis** (2,2 min) |
| Même lanceur sur `workbench.spec.cjs` (sans le test « demo, hostile » qui réécrit la capture du README) | 5 réussis, **1 échec** : voir « Contrat modifié » |

Chaque serveur de test a un dossier de données vide, une base claude-tap absente, des racines Claude/Codex vides et un `HOME` temporaire, en plus de `--no-capture`. Les ports sont libres. Les captures d'écran (375/768/1440) sont dans `.runtime/remediation-ui/shots/`. Les tests surveillent `pageerror` et la console : aucune erreur ni alerte inattendue.

## Constats confirmés et corrections

| ID | Cause racine | Correction | Preuve (test) |
| --- | --- | --- | --- |
| D-1 | La fiche fermée gardait son contenu ; `liveTick` ne rafraîchissait pas une fiche ouverte ; seules les relations sortantes étaient dessinées | Fiche rafraîchie après chaque lecture (`refreshDetail`), vidée à la fermeture, relations entrantes (« est remplacée par… ») calculées depuis les entrées | 3 tests D-1 : la fiche passe à « Remplacée » sans recharger, lien entrant visible et navigable |
| D-2 | Message brut anglais, aucune issue | Traduction centralisée (`frenchMessage`), erreur 409 reconnue, bouton « Charger la version actuelle » qui garde le brouillon et met à jour la révision ; pour une revue déjà faite, le formulaire se bloque et l'explique | 2 tests D-2 (édition puis réenregistrement : révision 3 ; revue : bouton désactivé) |
| D-3 (côté interface) | Filtre local sensible aux accents | Normalisation NFD, casse, espaces de bord. **La recherche serveur reste à l'agent store.** | Test P3 recherche : `elephant`, `ELEPHANT`, ` cafe `, `CAFÉ` |
| D-4 | À ≤650 px : bouton Git masqué, « + » absolu sur les onglets, pastille déformée. À 768 px, « + » recouvrait la liste | Barre latérale en flex, Git visible (≥40 px), « + » dans le flux, onglets défilants avec fondu indiquant la suite, actions du haut qui passent à la ligne ; « + » desktop recadré | 3 tests (375/768/1440) : aucun chevauchement, pas de débordement, cibles ≥24 px (40 px tactile), chaque onglet atteignable |
| D-5 | La liste des projets n'était lue qu'au chargement | `pollProjects` à chaque tick : le sélecteur apprend le nouveau projet, sans changer la sélection ni les brouillons ; depuis l'accueil vide, le premier projet est sélectionné | 2 tests D-5 |
| D-6 | Étiquette « claude-tap » pour tout, compteur = toutes les sources techniques, JSON brut visible | `sourceParts` : seules les vraies preuves sont comptées ; étiquette « Transcription locale Claude Code/Codex » pour le repli natif ; provenance lisible en français ; données techniques repliées | Test D-6 sur des entrées au format exact de `capture.py` (1 source, pas de JSON visible, `<img onerror>` reste du texte) |
| D-7 | Échap, fond ou Annuler fermaient sans condition | Détection de brouillon (`draftOf`), `confirm` français ; Échap intercepté en capture, pour que deux Échap de suite ne passent pas | Test D-7 : Échap ×2, fond, Annuler refusés ; sans brouillon, fermeture directe |

### P3 de l'interface traités

- **Messages** : erreurs techniques ou anglaises traduites ou génériques (« Cette demande n'est pas valide… ») ; test avec traceback simulé et « Project not found ».
- **Occupation** : bouton désactivé avec libellé d'action (« Importation en cours… »), `aria-busy` sur le formulaire.
- **État périmé** : erreur d'import, résultat et erreurs de formulaire effacés à chaque envoi ; toast retiré au changement de vue ; titre de page = vue + projet.
- **Libellés** : « Confirmer l'écart » (cohérent avec « Écarter ») ; vide des filtres honnête ; pluriel du pied de page ; deux listes d'historique nommées.
- **Capture** : « Suspendre » désactivé si la capture est désactivée ; confirmation avant d'exclure le dossier du projet affiché.
- **Graphe** : pages bornées de 48 nœuds, connaissances liées d'abord, filtre texte/statut, bouton « Afficher N de plus », surface limitée à 70 vh. Test sur 300 entrées.

## Contrat modifié (à intégrer par la racine)

1. **A-8 est déjà appliqué par le store** : « Seule une connaissance acceptée peut être remplacée ». L'interface n'offre donc plus « Remplacer » que pour une connaissance acceptée, avec une note pour une proposition.
2. **`tests/browser/workbench.spec.cjs` (non modifié, hors périmètre) échoue** à la ligne 36 : il remplace une hypothèse encore *proposée*. Il doit d'abord l'accepter (ou créer l'entrée acceptée). Échec constaté : le formulaire reste ouvert avec ce message.
3. Les messages anglais du store (`Entry changed…`) sont traduits côté client par motifs ; une traduction côté serveur serait plus robuste, et le test s'appuie sur « modifiée entre-temps ».

## Non résolu ou limité

- **Non vérifié contre l'original** : les fichiers ne sont pas commités, donc pas de rejeu des tests sur l'ancien code. Les échecs rencontrés pendant le développement (fiche ouverte non rafraîchie, `form.id` masqué par `<input name="id">`) ont été des échecs réels.
- **Recherche serveur** (D-3 côté `search_memory`), fiche de reprise en anglais, UUID dans la reprise, squelette vide sur requête sans résultat (D-9) : back-end, non touchés.
- **D-12** : la vue Capture lit encore la vraie base sur un serveur `--no-capture` (back-end). Les tests passent par des variables d'environnement isolées.
- **Graphe** : arêtes toujours dessinées sous les nœuds (pas de routage), pas de zoom ni de déplacement ; le « bornage + filtre » est la seule aide.
- **Démo** toujours accessible uniquement depuis l'état vide ; avertissement console « form not connected » non reproduit.
- **Annulation implicite par `confirm`** : cohérent avec l'existant, mais boîte native non stylée.
- Pas de lecteur d'écran testé ; Chromium seul. Le test D-5 « depuis l'accueil » attend jusqu'à 15 s (cadence de 6 s).
- Un script temporaire, `.runtime/remediation-ui/debug1.cjs`, reste (non versionné). Les dossiers de test du lanceur sont conservés dans `.runtime/remediation-ui/`.
