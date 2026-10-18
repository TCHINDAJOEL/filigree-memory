# Revue indépendante pedagogie

Modèle rapporté : claude-haiku-5-5

**Verdict :** deux défauts bloquent un débutant au démarrage (points 1 et 2). Le point 3 l'empêche de savoir ce qu'il doit faire lui-même. Les autres sont corrigeables. Je n'ai pas exécuté les commandes : cette relecture repose sur la lecture du texte.

1. **Page 3, « Ouvrir et relancer ».** Le guide donne l'URL `http://127.0.0.1:61300` sans dire de lancer le serveur. Le lanceur n'apparaît qu'« après un redémarrage ».
   *Correction :* faire du lanceur l'étape 1, avant l'URL.

2. **Page 3, lanceur.** `& "E:/test_memoire/livrables/Demarrer_atelier.ps1"` échoue avec la politique d'exécution PowerShell par défaut (Restricted). Le texte dit aussi « à côté du guide » sans donner le chemin du guide.
   *Correction :* écrire `powershell -ExecutionPolicy Bypass -File "E:/test_memoire/livrables/Demarrer_atelier.ps1"` et citer le chemin exact du guide.

3. **Pages 7 à 10, §6, §7 et §9.** Les prompts et étapes demandent de créer une proposition ou d'accepter une note déjà présente dans l'état livré : la proposition de l'architecte est déjà acceptée, et la méthode Agora est déjà à examiner. Un lecteur qui suit ces étapes sur Atlas ou Agora livrés crée des doublons. L'indication « créez Atlas Essai » n'apparaît qu'à la fin du §7.
   *Correction :* mettre en tête du §6 un encadré : « Ne rejouez pas ces étapes sur Atlas ou Agora livrés. Travaillez dans Atlas Essai, copie des trois notes initiales. » Pour chaque étape déjà faite dans l'atelier, écrire « déjà fait : observez le résultat ».

4. **Page 11, §10 étapes 3-4, et page 12, étape 2.** Le guide demande d'ajouter la source avant d'enregistrer. Le contrôle du §11 cherche pourtant « la révision qui ajoute la source », et la figure 8 dit qu'elle a été ajoutée par une seconde révision. Le lecteur ne trouvera pas cet historique.
   *Correction :* préciser que la chronologie montre une ou deux entrées selon que la source est ajoutée à la création ou ensuite, ou retirer la mention de révision du contrôle.

5. **Page 12, étape 3.** Le libellé « Historical alternatives — NOT CURRENT » est en anglais dans un guide français, et rien n'indique qu'il s'agit du texte exact affiché.
   *Correction :* donner le libellé exact entre guillemets, suivi d'une traduction entre parenthèses, après vérification à l'écran.

6. **Page 19, « Bilan ».** Le paragraphe mêle des détails internes (« changement de préférence », assertion d'immutabilité corrigée) qui relèvent du dossier `.aiwg/testing`. Le tableau emploie trois formules (« Vérifié », « Vérifié via UI », « Vérifié en réel ») sans dire qui a vérifié.
   *Correction :* déplacer l'incident vers le rapport de vérification, et normaliser en « Vérifié (interface) », « Vérifié (MCP réel) » ou « Non exécuté ».

7. **Page 15, étape 2.** La commande `serve` ne précise pas le port. Le lecteur ne sait pas s'il faut ouvrir 61300 ou 7820.
   *Correction :* indiquer l'URL affichée au démarrage, ou l'option de port utilisée.

Points vérifiés à la lecture : la séparation entre les trois dossiers projet est claire, les figures sont numérotées de 1 à 11 sans trou, et la règle « l'import crée une proposition, pas une décision » est affirmée de façon cohérente.