# Vérification de l’atelier du guide

17 octobre 2026. Données fictives isolées ; serveur 61300 sans capture. Produit inchangé.

Trois dossiers distincts, 14 connaissances finales : Atlas 4, Agora 4, Orion 6.
Deux clients Claude Sonnet réels via claude-tap et MCP ont ajouté chacun une proposition, dans Atlas et Agora. Un client Claude Haiku neuf a relu Atlas après acceptation et refus via Playwright et a cité les trois identifiants attendus sans modifier la mémoire. Les décisions de chef de projet sont des interactions automatisées de démonstration autorisées, pas une validation personnelle de l’utilisateur.

Playwright réel : acceptation motivée, refus motivé, remplacement JSON par CSV, maintien SQLite, révision avec source, graphe, chronologie, recherche, import proposé et capture désactivée. Captures et journaux dans .runtime/guide-atelier, non publiés. Le script verify_workshop.py a contrôlé les états finaux et l’affectation des notes MCP.

Incident du harnais : assertion globale « autre projet inchangé » inadaptée aux deux écrivains parallèles. Elle a échoué pour Agora car Atlas était modifié simultanément. Résultat Claude et proposition Agora vérifiés a posteriori, sans nouvel appel ni prétention d’immutabilité globale. La lecture Haiku séquentielle a, elle, vérifié l’immutabilité de tous les projets. Les compteurs de traces TAP peuvent répéter les appels dans des contextes successifs et ne sont pas des décomptes uniques.

Les futures applications boutique, inscription et stock n’ont pas été développées ni testées dans cet atelier. Les tests métier sont des recettes proposées. Capture native, Git distant et client Codex ne sont pas retestés ici ; voir le rapport de livraison pour les preuves antérieures.
