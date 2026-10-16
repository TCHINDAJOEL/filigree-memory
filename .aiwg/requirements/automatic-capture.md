# Précision utilisateur — activation automatique par dossier

Date : 16 octobre 2026. Source : messages utilisateur de cette session. Statut : exigence confirmée ; implémentation Sonnet en cours, vérification à réaliser.

## Ce qui devient indispensable

La mémoire s'active lorsque Claude, Codex ou un client compatible travaille dans un dossier de projet local. Elle reste attachée à ce dossier, quels que soient l'agent et la session. L'import manuel demeure une fonction de récupération, pas le parcours principal.

Le raccordement à claude-tap doit être étudié à partir de son code. Une connaissance capturée doit permettre de remonter au record tap, à la session native lorsqu'elle est connue et au dossier identifié. Ni le nom du dossier, ni la dernière session, ni une proximité temporelle ne suffisent à établir cette correspondance.

## Histoires complémentaires

| ID | Comportement attendu | Preuve de sortie |
| --- | --- | --- |
| US-11 | Après démarrage du moniteur, une session dans un dossier réel identifié crée automatiquement sa mémoire si nécessaire. | Fixture session native + record tap, sans création manuelle préalable |
| US-12 | Claude et Codex dans le même dossier alimentent le même projet ; deux dossiers restent isolés. | Test deux clients/deux projets avec ordre temporel entrelacé |
| US-13 | Chaque observation capturée conserve sa provenance de collecte, sans devenir une décision acceptée. | Source et identifiants inspectables dans les fichiers et l'interface |
| US-14 | Une session sans rattachement exact reste en attente et peut être rattachée explicitement. | Aucun contenu dans un projet arbitraire ; contrôle utilisateur visible |
| US-15 | Pause, exclusion, reprise et redémarrage ne perdent pas silencieusement l'état et ne dupliquent pas les événements. | Tests de curseurs, crash, déduplication et contrôles |
| US-16 | Le moniteur expose la compatibilité réelle du client et du schéma tap. | Statuts absent, incompatible, actif ou en attente ; pas de faux succès |

## Arbitrages de l'orchestrateur

L'ADR-0002 révision 2 proposait de ne jamais créer automatiquement un projet non enregistré. Cette restriction contredit l'instruction utilisateur. **La création automatique est retenue lorsque la session fournit une correspondance exacte vers un dossier local valide et unique.** Le défaut d'identification entraîne toujours une attente, jamais une déduction approximative.

Les appels et résultats d'outils accessibles sont utiles à l'histoire des tentatives et validations. Leur collecte peut produire des observations bornées et expurgées ; elle n'autorise aucune exécution. Le raisonnement interne caché, les credentials et les instructions système ne sont pas des connaissances à collecter.

La détection passive exige un moniteur en cours d'exécution. Un mécanisme de démarrage local peut être installé explicitement. L'accès aux conversations d'une application de bureau n'est annoncé que si une source locale compatible existe. La présence d'un processus seul ne prouve rien.

La lecture de la mémoire par les agents nécessite un raccordement MCP initial. Le produit doit l'expliquer clairement ; il ne doit ni modifier leurs configurations silencieusement ni prétendre injecter un contexte qu'il n'a pas transmis.

## Organisation confirmée

Codex : orchestration, décisions d'intégration et publication. Claude Opus : conception et étude upstream. Claude Sonnet : implémentation. Claude Haiku : exécution des tests. Tous les appels Claude passent par `claude-tap` sur le PC de l'utilisateur.
