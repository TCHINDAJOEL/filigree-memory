# Constats d'intégration à traiter avant livraison

## F-UI-01 — sélection du projet et requête en cours

La capture navigateur montre le sélecteur sur « La mémoire d'un projet » alors que le titre et les données affichent encore le projet précédent. Le test attendait un titre générique déjà présent avant la fin de `refresh`. Cela révèle aussi un risque réel : le bouton Ajouter reste disponible pendant le changement de projet et peut ouvrir une saisie rattachée à l'ancien état global.

À corriger après le build capture : bloquer les opérations d'écriture pendant un changement explicite de projet et capturer l'identité du projet au début de chaque mutation. La mise à jour automatique ne doit jamais vider un formulaire en cours. Le test doit attendre `#project-name` correspondant au projet sélectionné avant d'agir et de prendre une capture. Ne pas supprimer le contrôle XSS/mobile.

## F-UI-02 — libellé de journal technique

`events.imported` n'est pas traduit dans `eventMarkup` (on voit le code technique dans la chronologie). Utiliser « Traces importées ».

## F-PACKAGE-01 — version finale

La capture automatique change les contrats publics. Reconstruire et réinstaller le wheel après les modifications, ne pas réutiliser la preuve du paquet antérieur.
