# Capture automatique — critères de sortie

Auteur : orchestrateur. Date : 16 octobre 2026. Statut : plan de vérification, aucune réussite implicite. Complète US-11 à US-16 et la stratégie du socle. Revue indépendante et résultats à relier au gate.

## Parcours qui justifient la livraison

1. Démarrer le moniteur sur des racines et une base TAP synthétiques isolées. Les sessions déjà présentes constituent une ligne de base ; leur historique n'est pas importé.
2. Ajouter une nouvelle session Claude avec un identifiant natif exact et un dossier existant. Ajouter son échange TAP. La mémoire se crée sans enregistrement préalable du projet. Les observations restent proposées et conservent les identifiants de provenance.
3. Entrelacer une session Codex dans le même dossier et une session Claude dans un autre dossier. Vérifier un seul projet pour le premier dossier, un autre pour le second, sans contenu croisé.
4. Présenter un identifiant absent, contradictoire ou associé à plusieurs dossiers. Vérifier l'attente, puis le rattachement explicite. Ni la proximité temporelle ni le nom du dossier ne doivent résoudre l'ambiguïté.
5. Redémarrer le moniteur et rejouer un record après une interruption entre import et sauvegarde du curseur. Vérifier l'absence de doublon. Vérifier pause/reprise, exclusion/inclusion et l'exclusion de la mémoire du moniteur lui-même.
6. Décoder un record compact valide ; refuser hash, taille, version et chemin invalides. Vérifier que la base source n'a subi aucune écriture. Les erreurs doivent être visibles et ne pas bloquer les autres sources.
7. Préserver les textes exprimés, appels et résultats d'outils utiles. Écarter blocs de pensée cachée et instructions système. Un texte source malveillant reste une donnée inerte.
8. Vérifier le parcours d'un client lancé directement, sans TAP, lorsqu'un adaptateur natif est disponible. Distinguer explicitement capture native et TAP ; ne pas annoncer ce parcours s'il n'est pas implémenté et exécuté.
9. Dans le navigateur, créer ou rattacher un dossier, inspecter le statut de capture, changer de projet pendant une requête, puis continuer une saisie pendant un rafraîchissement. Aucune mutation ne doit cibler l'ancien projet par accident et aucun brouillon ne doit disparaître.
10. Reconstruire le paquet, l'installer hors du dépôt et vérifier CLI, ressources statiques, HTTP et MCP. Les tests utilisent `--no-capture` ou des sources explicitement synthétiques.

## Passage à un autre agent

La preuve de transport MCP et la compréhension d'un modèle sont deux résultats distincts. Le scénario souhaité crée une décision ancienne remplacée, une preuve et une question ouverte dans une mémoire synthétique. Un autre appel Claude Haiku reçoit la reprise via le raccordement documenté et doit citer le choix actuel, l'alternative historique et l'incertitude sans les confondre. Sans exécution de ce scénario, la livraison doit l'indiquer comme non vérifié.

## Répartition

Sonnet écrit les cas et corrige les défauts. Haiku exécute les commandes et rapporte sorties et codes réels. Opus et l'orchestrateur examinent indépendamment les contrats et les écarts. L'orchestrateur synthétise les preuves et décide du gate ; un test du socle antérieur ne valide pas les nouveaux modules.
