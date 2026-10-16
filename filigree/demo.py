"""Fictional demonstration grounded in the product's central acceptance scenario."""

import hashlib
import os
import tempfile
from pathlib import Path


def _demo_folder(store) -> str:
    """One stable, empty demo folder per memory directory: repeated runs never litter the temp directory."""
    name = "filigree-demo-" + hashlib.sha256(os.path.normcase(str(store.root)).encode("utf-8")).hexdigest()[:12]
    folder = Path(tempfile.gettempdir()) / name
    folder.mkdir(exist_ok=True)
    return str(folder)


def seed_demo(store, folder=None):
    """The demo gets its own empty, real folder; demo projects are never fed by automatic capture.

    Idempotent for the default folder: when the demo project bound to it already exists, it is returned unchanged.
    An explicit `folder` always creates a new demo project."""
    if folder is None:
        folder = _demo_folder(store)
        key = store.canonical_folder(folder)["key"]
        existing = next((project for project in store.list_projects() if project.get("demo") and (project.get("folder") or {}).get("key") == key), None)
        if existing:
            return existing
    project = store.create_project("La mémoire d'un projet", "Démonstration fictive : suivre un choix, son recadrage et les preuves qui permettent de reprendre.", folder=folder, demo=True)
    pid = project["id"]
    def entry(title, body, kind="decision", status="proposed", **extra):
        return store.create_entry(pid, {"title": title, "body": body, "kind": kind, "status": status, "episode": "Concevoir la continuité", "agent": "Démonstration", "tags": ["démo", "continuité"], "sources": [{"label": "Scénario fictif de démonstration", "excerpt": body, "uri": ""}], **extra})
    goal = entry("Une mémoire pour les humains et les agents", "Une personne qui rejoint le projet doit comprendre pourquoi il a cette forme, les pistes écartées et ce qui reste incertain.", "constraint", "accepted")
    option = entry("Utiliser Basic Memory comme socle", "Proposition initiale : réutiliser Basic Memory. Cette proposition n'est pas un choix technique validé.", "hypothesis")
    correction = entry("Définir la méthode avant les outils", "Le cadrage est corrigé : commencer par les situations de travail et les critères de réussite. Le choix du moteur reste ouvert.", "correction", "accepted", relations=[{"target": option["id"], "type": "contradicts"}, {"target": goal["id"], "type": "supports"}])
    entry("Le socle technique reste à choisir", "Ne pas présenter Basic Memory comme une décision. Évaluer les outils sur la reprise par un humain et un second agent.", "decision", "accepted", relations=[{"target": correction["id"], "type": "supports"}])
    entry("La reprise conserve-t-elle le recadrage ?", "Préparer un épisode de test, produire une fiche de reprise et vérifier qu'elle distingue la proposition du choix accepté.", "question")
    entry("Proposer une procédure de passation", "À chaque changement d'agent : objectif, décisions applicables, alternatives, incertitudes, prochaine action et sources. À confirmer sur un second projet.", "procedure")
    return store.get_project(pid)
