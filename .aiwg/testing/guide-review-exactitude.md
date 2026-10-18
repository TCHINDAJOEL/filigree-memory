# Revue indépendante exactitude

Modèle rapporté : claude-haiku-5-5

**Verdict : défauts bloquants présents (1 à 3).**

**Bloquants**

1. **Pages 6 à 8, état de la proposition de l'architecte.** La page 6 dit qu'elle est « déjà acceptée » dans l'état livré. La légende de la figure 4 dit « avant son acceptation ». L'étape 1 de la page 7 demande de l'accepter. Le bilan parle de « deux connaissances acceptées » sans dire lesquelles. **Correction :** indiquer que la note « Réserver un retrait sans paiement en ligne » est déjà acceptée (cadrage et architecte font les deux acceptées). Transformer l'étape 1 en vérification de la note et de sa raison. Réserver l'acceptation au parcours « Atlas Essai ».

2. **Pages 15 et 17, capture.** Le guide ne décrit que le chemin claude-tap et « les traces locales compatibles ». La référence produit dit que le repli natif est activé par défaut : `filigree serve` lit aussi les transcriptions locales de Claude Code et de Codex lancés directement. Ce point touche à la confidentialité. **Correction :** ajouter ce comportement, la commande `filigree capture fallback off`, le cas du réglage hérité `"native_fallback": false`, et le fait que le repli n'a été vérifié que par un lancement réel de Claude Code sur un projet synthétique.

3. **Page 19, ligne « Le graphe et la reprise conservent JSON historique ».** Elle est marquée « Vérifié ». Les preuves couvrent le graphe Orion, mais la seule reprise exécutée est celle d'Atlas par Haiku. **Correction :** scinder la ligne. Le graphe reste « Vérifié via UI ». La reprise Orion passe en « Non exécuté ».

**Non bloquants**

4. **Page 9, « délai de 24 ou 48 heures ».** Cette valeur n'apparaît ni dans le texte du guide ni dans les preuves. **Correction :** citer la note qui la porte, ou la retirer.

5. **Page 5, « Écrivez la raison de la révision ».** Le produit rend la justification facultative. **Correction :** « Ajoutez si utile une raison (facultative) ».

6. **Page 17, « schéma compatible » pour claude-tap.** Le produit n'accepte que le schéma 4. **Correction :** écrire « schéma 4 uniquement ».

7. **Page 17, dépannage.** Il manque le cas « sans dossier » d'un projet ancien, avec « Rattacher un dossier », et la commande `filigree capture link`. **Correction :** ajouter les deux entrées.

8. **Page 16, plage de budget « entre 500 et 100000 ».** Cette plage n'est pas dans la référence produit. **Correction :** la vérifier dans le code ou la retirer.

9. **Page 13, import.** Le guide ne dit pas que le corps importé est copié dans la mémoire, alors que la référence le précise. **Correction :** ajouter une phrase dans la section Import, car c'est un point de confidentialité.

10. **Page 19, bilan.** « Assertion corrigée dans l'analyse » reste vague. **Correction :** préciser qu'il s'agit d'un défaut du harnais de test et non du produit, et qu'Agora a été vérifié a posteriori sans nouvel appel.