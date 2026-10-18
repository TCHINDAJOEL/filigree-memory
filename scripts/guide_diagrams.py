"""Draws the explanatory diagrams of docs/guide/ as standalone SVG files (no dependency).

    python scripts/guide_diagrams.py

SVG files are written to docs/guide/images/; `node scripts/guide_screenshots.cjs --diagrams` renders PNG copies for
the Word export. Text is French, like the workbench.
"""
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[1] / "docs" / "guide" / "images"
VIOLET, VIOLET_SOFT, INK, MUTED, LINE = "#6F5BD3", "#EEEAF8", "#1F1B2E", "#6B6559", "#B9B0DA"
GREEN, GREEN_SOFT, AMBER, AMBER_SOFT, RED_SOFT = "#2F6B4F", "#E6F2EC", "#A0661A", "#FBF1E1", "#F8E6E3"
FONT = "Segoe UI, Helvetica Neue, Arial, sans-serif"


class Svg:
    def __init__(self, width, height, title):
        self.width, self.height, self.parts = width, height, []
        self.title = title

    def add(self, text):
        self.parts.append(text)

    def box(self, x, y, w, h, lines, fill="#FFFFFF", stroke=LINE, bold_first=True, size=14, radius=10, align="middle", color=INK):
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        line_height = size + 6
        top = y + h / 2 - (len(lines) - 1) * line_height / 2 + size * 0.35
        anchor_x = x + w / 2 if align == "middle" else x + 14
        for index, line in enumerate(lines):
            weight = "600" if bold_first and index == 0 else "400"
            fill_color = color if index == 0 or not bold_first else MUTED
            font_size = size if index == 0 else size - 2
            self.add(f'<text x="{anchor_x}" y="{top + index * line_height:.1f}" text-anchor="{"middle" if align == "middle" else "start"}" font-size="{font_size}" font-weight="{weight}" fill="{fill_color}">{escape(line)}</text>')

    def label(self, x, y, text, size=13, color=MUTED, anchor="middle", weight="400"):
        self.add(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" font-weight="{weight}" fill="{color}">{escape(text)}</text>')

    def arrow(self, x1, y1, x2, y2, color=VIOLET, dashed=False, text=None, text_dy=-6):
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        self.add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="2"{dash} marker-end="url(#head-{color[1:]})"/>')
        if text:
            self.label((x1 + x2) / 2, (y1 + y2) / 2 + text_dy, text, size=12, color=color)

    def path(self, d, color=VIOLET, dashed=False):
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        self.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"{dash} marker-end="url(#head-{color[1:]})"/>')

    def render(self):
        heads = "".join(f'<marker id="head-{c[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
                        for c in (VIOLET, GREEN, AMBER, MUTED, "#A3452C"))
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" viewBox="0 0 {self.width} {self.height}" font-family="{FONT}" role="img" aria-label="{escape(self.title)}">'
                f'<title>{escape(self.title)}</title><defs>{heads}</defs><rect width="100%" height="100%" fill="#FBFAFE"/>' + "".join(self.parts) + "</svg>\n")


def architecture():
    s = Svg(1240, 720, "Architecture de Filigree : des applications d'IA à la mémoire du projet")
    s.label(620, 38, "Comment Filigree fonctionne", size=22, color=INK, weight="700")
    s.label(620, 62, "Tout se passe sur votre machine : lecture seule des traces, aucune requête vers un modèle, aucune donnée envoyée.", size=13)
    columns = [(30, "1. Vos applications"), (330, "2. Ce qu'elles écrivent"), (640, "3. filigree agent"), (990, "4. Mémoire et usages")]
    for x, title in columns:
        s.label(x + (120 if x < 900 else 110), 104, title, size=15, color=VIOLET, weight="700")
    apps = [("Claude Code", "terminal, IDE"), ("Claude Desktop", "onglet Code"), ("Codex CLI", "terminal"), ("Application Codex", "Codex Desktop, VS Code"), ("claude-tap", "proxy optionnel"), ("ChatGPT · claude.ai", "export de vos données")]
    files = [("~/.claude/projects/", "transcriptions .jsonl"), ("Claude/claude-code-sessions", "métadonnées seulement"), ("~/.codex/sessions/", "+ state_5.sqlite"), ("~/.codex/sessions/", "même format que la CLI"), ("traces.sqlite3", "base claude-tap"), ("conversations.json", "dans l'archive .zip")]
    for index, ((app, app_sub), (file, file_sub)) in enumerate(zip(apps, files)):
        y = 130 + index * 98
        s.box(30, y, 240, 64, [app, app_sub], fill=VIOLET_SOFT if index < 4 else "#FFFFFF")
        s.box(330, y, 250, 64, [file, file_sub], fill="#FFFFFF", size=13)
        s.arrow(272, y + 32, 326, y + 32)
    # The agent: every source enters through its left edge, at its own height
    s.add(f'<rect x="630" y="122" width="300" height="490" rx="14" fill="#FFFFFF" stroke="{VIOLET}" stroke-width="2.5"/>')
    steps = [(150, ["Collecteurs", "lecture seule, bornée"]), (240, ["Résolution", "dossier → projet, racines autorisées"]),
             (330, ["Capture par échange", "propositions (option)"]), (420, ["Journal d'activité", "activity.sqlite, 90 jours"]), (510, ["Fiches de session", "1 proposition par session"])]
    for y, lines in steps:
        s.box(650, y, 260, 60, lines, fill=VIOLET_SOFT if y < 300 else "#FFFFFF", size=13)
    for y1, y2 in ((210, 238), (300, 328), (480, 508)):
        s.arrow(780, y1, 780, y2)
    s.path("M 700 300 L 700 418")  # resolution also feeds the journal
    for index in range(5):
        y = 162 + index * 98
        s.arrow(582, y, 628, y)
    s.label(780, 600, "un seul processus par dossier de données", size=12)
    # Explicit import: below the agent, then up the bus
    s.box(650, 636, 260, 56, ["filigree import-export", "projet toujours choisi par vous"], size=13)
    s.arrow(582, 650, 646, 660, color=MUTED)
    # Proposals bus (x = 958) up to the memory
    for y in (360, 540):
        s.add(f'<line x1="912" y1="{y}" x2="958" y2="{y}" stroke="{VIOLET}" stroke-width="2"/>')
    s.add(f'<line x1="912" y1="664" x2="958" y2="664" stroke="{MUTED}" stroke-width="2"/>')
    s.add(f'<line x1="958" y1="664" x2="958" y2="190" stroke="{VIOLET}" stroke-width="2"/>')
    s.arrow(958, 190, 986, 190)
    s.add(f'<text x="972" y="430" font-size="12" fill="{VIOLET}" transform="rotate(-90 972 430)" text-anchor="middle">propositions</text>')
    # Memory and uses
    s.box(990, 140, 220, 96, ["Mémoire du projet", "Markdown portable", "propositions → revue humaine"], fill=GREEN_SOFT, stroke=GREEN, color=GREEN)
    uses = [(270, ["Interface web", "127.0.0.1:7820 · vous examinez"]), (360, ["Serveur MCP", "vos agents lisent et proposent"]), (450, ["Hook --inject", "connaissances acceptées"]), (540, ["Reprise · export · Git", "pour la personne suivante"])]
    for y, lines in uses:
        s.box(990, y, 220, 64, lines, size=13)
    for y in (238, 336, 426, 516):
        s.add(f'<line x1="1100" y1="{y}" x2="1100" y2="{y + 30 if y == 238 else y + 22}" stroke="{LINE}" stroke-width="1.5"/>')
    return s


def session_flow():
    s = Svg(1240, 440, "Le parcours d'une session d'agent dans Filigree")
    s.label(620, 38, "Le parcours d'une session", size=22, color=INK, weight="700")
    s.label(620, 62, "De votre commande « claude » à la connaissance acceptée que lira l'agent suivant.", size=13)
    steps = [("Vous lancez", "claude ou codex", "dans ~/code/app"), ("L'application écrit", "sa transcription", "sur votre disque"), ("L'agent Filigree lit", "les nouvelles lignes", "toutes les 5 s"),
             ("Dossier → projet", "« app » trouvé", "(racines autorisées)"), ("Journal d'activité", "demandes, fichiers,", "tests, erreurs, commits"), ("Fiche de session", "après 10 min d'inactivité", "ou fin de session")]
    for index, lines in enumerate(steps):
        x = 30 + index * 200
        s.box(x, 110, 176, 96, list(lines), fill=VIOLET_SOFT if index < 3 else "#FFFFFF", size=14)
        s.label(x + 88, 98, str(index + 1), size=13, color=VIOLET, weight="700")
        if index < 5:
            s.arrow(x + 178, 158, x + 198, 158)
    s.arrow(1118, 208, 1118, 268)
    s.box(990, 270, 220, 80, ["Vous examinez", "Accepter · Écarter · Modifier"], fill=AMBER_SOFT, stroke=AMBER, color=AMBER)
    s.arrow(988, 310, 742, 310, color=GREEN, text="acceptée")
    s.box(520, 270, 220, 80, ["Connaissance actuelle", "dans la mémoire du projet"], fill=GREEN_SOFT, stroke=GREEN, color=GREEN)
    s.arrow(518, 310, 282, 310, color=GREEN, text="MCP · hook --inject · reprise")
    s.box(60, 270, 220, 80, ["L'agent suivant", "repart du bon contexte"], fill=GREEN_SOFT, stroke=GREEN, color=GREEN)
    s.label(620, 400, "Ce qui n'est jamais conservé : lignes de commande complètes, raisonnement interne du modèle, blocs injectés, historique antérieur au premier lancement.", size=12)
    s.label(620, 420, "Les résumés sont expurgés (secrets connus masqués) avant d'être coupés à 280 caractères.", size=12)
    return s


def review_cycle():
    s = Svg(1240, 380, "Cycle de vie d'une connaissance")
    s.label(620, 38, "Personne d'autre que vous ne décide", size=22, color=INK, weight="700")
    s.label(620, 62, "Tout ce qui vient d'un agent, d'une capture ou d'un import entre comme proposition ; seule l'interface locale accepte.", size=13)
    sources = [("Capture automatique", 100), ("Agent via MCP", 180), ("Import / export de chat", 260)]
    for text, y in sources:
        s.box(40, y, 230, 54, [text], size=14)
        s.arrow(272, y + 27, 396, 207)
    s.box(400, 170, 200, 74, ["À examiner", "proposed"], fill=AMBER_SOFT, stroke=AMBER, color=AMBER)
    s.arrow(602, 190, 756, 130, color=GREEN, text="Accepter")
    s.arrow(602, 228, 756, 284, color="#A3452C", text="Écarter", text_dy=18)
    s.box(760, 96, 200, 74, ["Acceptée", "accepted : actuelle"], fill=GREEN_SOFT, stroke=GREEN, color=GREEN)
    s.box(760, 250, 200, 74, ["Écartée", "rejected : historique"], fill=RED_SOFT, stroke="#A3452C", color="#A3452C")
    s.arrow(962, 133, 1036, 133, color=MUTED)
    s.box(1040, 96, 170, 74, ["Remplacée", "par une décision plus récente"], fill="#F1EFF5", stroke=MUTED, color=MUTED, size=13)
    s.label(1125, 200, "jamais effacée :", size=12)
    s.label(1125, 218, "reste dans l'historique", size=12)
    s.label(620, 356, "Chaque changement crée une révision. Les reprises séparent l'actuel (acceptée), l'incertain (à examiner) et l'historique (écartée, remplacée).", size=12)
    return s


def coverage():
    s = Svg(1240, 510, "Ce que Filigree fait pour chaque application")
    s.label(620, 38, "Une application, trois façons de se connecter", size=22, color=INK, weight="700")
    headers = ["Application", "Observée automatiquement", "Lit la mémoire (MCP)", "Hooks / contexte"]
    rows = [("Claude Code (CLI, IDE)", "oui : transcriptions", "oui : claude mcp add", "oui : --inject au démarrage"),
            ("Claude Desktop, onglet Code", "oui, via la transcription Claude Code", "oui : claude_desktop_config.json", "non vérifié"),
            ("Claude Desktop, conversation", "non", "oui : claude_desktop_config.json", "non"),
            ("Codex CLI", "oui : rollouts + state", "oui : codex mcp add", "signal notify (sans contexte)"),
            ("Application Codex / VS Code", "oui : mêmes fichiers ~/.codex", "même config.toml que la CLI", "non vérifié"),
            ("claude.ai · ChatGPT (web)", "non", "non (MCP local impossible)", "non : import d'export")]
    widths, x0, y0 = [300, 300, 300, 280], 30, 84
    def cell(x, y, w, text, header=False, ok=None):
        fill = VIOLET if header else (GREEN_SOFT if ok == "oui" else AMBER_SOFT if ok == "partiel" else RED_SOFT if ok == "non" else "#FFFFFF")
        s.add(f'<rect x="{x}" y="{y}" width="{w}" height="54" fill="{fill}" stroke="#FFFFFF" stroke-width="3"/>')
        s.label(x + 14, y + 32, text, size=14 if header else 13, color="#FFFFFF" if header else INK, anchor="start", weight="600" if header else "400")
    x = x0
    for header, width in zip(headers, widths):
        cell(x, y0, width, header, header=True)
        x += width
    for r, row in enumerate(rows):
        x = x0
        for c, (text, width) in enumerate(zip(row, widths)):
            status = None if c == 0 else ("oui" if text.startswith(("oui", "même")) else "non" if text.startswith("non") else "partiel")
            cell(x, y0 + 54 * (r + 1), width, text, ok=status)
            x += width
    s.label(620, 492, "Vérifiez votre poste avec « filigree probe » : il compte, en lecture seule, les sessions lisibles par application.", size=12)
    return s


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in (("schema-architecture", architecture), ("schema-session", session_flow), ("schema-revue", review_cycle), ("schema-applications", coverage)):
        (OUT / f"{name}.svg").write_text(build().render(), encoding="utf-8")
        print("ok", name + ".svg")
