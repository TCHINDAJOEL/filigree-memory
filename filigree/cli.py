"""Human and agent entry points share the same portable store."""

import argparse
import json
import math
import os
from pathlib import Path
import site
import sys
import time

from . import __version__
from .demo import seed_demo
from .importers import parse_import, parse_text
from .store import Store

MAX_INTERVAL = 86400.0


def _interval(text):
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("nombre de secondes attendu") from None
    if not math.isfinite(value) or value > MAX_INTERVAL:
        raise argparse.ArgumentTypeError(f"nombre fini de secondes (au plus {int(MAX_INTERVAL)}) attendu")
    return value


def _port(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("numéro de port attendu") from None
    if not 0 <= value <= 65535:
        raise argparse.ArgumentTypeError("port entre 0 et 65535 attendu")
    return value


def _toml_string(value):
    """TOML basic string: only the characters TOML requires are escaped, so non-ASCII text stays literal UTF-8."""
    escapes = {"\\": "\\\\", '"': '\\"', "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}
    return '"' + "".join(escapes.get(ch) or (f"\\u{ord(ch):04X}" if ord(ch) < 0x20 or ord(ch) == 0x7F else ch) for ch in value) + '"'


def _source_checkout():
    """Directory to put on PYTHONPATH when this package runs from a source tree rather than an installed location."""
    parent = Path(__file__).resolve().parent.parent
    installed = {Path(p).resolve() for p in [*site.getsitepackages(), site.getusersitepackages()] if p}
    if parent in installed or parent.name in {"site-packages", "dist-packages"}:
        return None
    return parent


def mcp_config(client, data_dir):
    """Configuration text for the user to install themselves. Filigree writes no agent file.

    It names the interpreter running this command and, when the package is not installed, the source directory, so the
    entry launches `python -m filigree` from any working directory."""
    arguments = ["-m", "filigree", "--data-dir", str(Path(data_dir).resolve()), "mcp"]
    command = sys.executable or "python"
    checkout = _source_checkout()
    if client == "claude":
        entry = {"command": command, "args": arguments}
        if checkout:
            entry["env"] = {"PYTHONPATH": str(checkout)}
        return json.dumps({"mcpServers": {"filigree": entry}}, indent=2, ensure_ascii=False)
    lines = ["[mcp_servers.filigree]", "command = " + _toml_string(command), "args = [" + ", ".join(_toml_string(a) for a in arguments) + "]"]
    if checkout:
        lines.append("env = { PYTHONPATH = " + _toml_string(str(checkout)) + " }")
    return "\n".join(lines)  # text-mode stdout turns LF into the platform's line ending: never a second CR


def _report_waiting(message, previous):
    if message != previous:
        print(f"Waiting for a complete readable export: {message}", file=sys.stderr, flush=True)
    return message


def capture_command(store, args):
    from .capture import Capture
    capture = Capture(store)
    action = args.action
    if action == "run":
        raise SystemExit(capture.run_foreground(max(args.interval, 0.5), args.once))
    if action == "status":
        result = capture.status()
    elif action == "pending":
        result = capture.pending()
    elif action == "link":
        result = capture.link(args.key, args.project_id, args.import_history)
    elif action == "unlink":
        result = capture.unlink(args.key)
    elif action in {"pause", "resume"}:
        capture.set_paused(action == "pause", args.project or "")
        result = {"paused" if action == "pause" else "resumed": args.project or "all"}
    elif action in {"exclude", "include"}:
        capture.set_excluded(str(args.folder), action == "exclude")
        result = {action + "d": str(args.folder)}
    elif action in {"enable", "disable"}:
        capture.set_enabled(action == "enable")
        result = {"enabled": action == "enable"}
    elif action == "fallback":
        capture.set_native_fallback(args.mode == "on")
        result = {"native_fallback": args.mode == "on"}
    elif action == "start":
        result = {"result": capture.start_background()}
    else:
        result = {"result": capture.request_stop()}
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _launcher() -> list[str]:
    """How a hook or service starts this Filigree: the installed module, or this source checkout."""
    python = sys.executable or "python"
    checkout = _source_checkout()
    if checkout:
        return [python, "-c", f"import sys;sys.path.insert(0,{str(checkout)!r});from filigree.cli import main;main()"]
    return [python, "-m", "filigree"]


def v2_command(args) -> dict:
    """probe / status / service / hooks: JSON reports; installation only on an explicit action."""
    data_dir = args.data_dir.expanduser().resolve()
    if args.command == "probe":
        from .probe import run_probe
        return run_probe()
    if args.command == "service":
        from . import service
        planned = service.current_plan(data_dir)
        if args.service_action == "status" or args.dry_run:
            return {**service.status(planned, service.SystemRunner()), "plan": {key: value for key, value in planned.items() if key in {"command", "path", "text", "description"}}}
        return (service.apply if args.service_action == "install" else service.remove)(planned, service.SystemRunner())
    if args.command == "hooks":
        from . import hooks
        if args.hooks_action == "status":
            return hooks.status(data_dir)
        if not args.client:
            raise ValueError("--client claude|codex est requis pour install/uninstall.")
        return hooks.change(args.client, args.hooks_action, data_dir, _launcher(), inject=args.inject, dry_run=args.dry_run)
    from . import hooks, service
    from .activity import ActivityLog, journal_path
    from .agent import running_agent
    from .capture import Capture
    store = Store(data_dir)
    settings, error = Capture(store).settings()
    try:
        autostart = service.status(service.current_plan(data_dir), service.SystemRunner())
    except (ValueError, OSError) as exc:
        autostart = {"installed": False, "error": str(exc)}
    journals = {project["id"]: ActivityLog(journal_path(store, project["id"])).stats() for project in store.list_projects() if journal_path(store, project["id"]).exists()}
    artifacts = sorted(path.relative_to(data_dir).as_posix() for folder in (".runtime", ".capture") for path in (data_dir / folder).glob("*") if path.is_file())
    return {"version": __version__, "data_dir": str(data_dir), "agent": running_agent(data_dir), "autostart": autostart, "hooks": hooks.status(data_dir),
            "capture": {"enabled": settings["enabled"], "settings_error": error, "allowed_roots": settings["allowed_roots"], "activity": settings["activity"]},
            "journals": journals, "artifacts": artifacts}


def main(argv=None):
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="filigree", description="Local living project memory for humans and agents.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("FILIGREE_DATA_DIR", Path.home() / ".filigree")))
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Open the local web workbench")
    serve.add_argument("--port", type=_port, default=7820)
    serve.add_argument("--no-capture", action="store_true", help="Do not start the automatic capture monitor")
    create = sub.add_parser("create", help="Create a memory project bound to an existing absolute folder")
    create.add_argument("name")
    create.add_argument("--folder", required=True, type=Path, help="Existing absolute project folder")
    create.add_argument("--description", default="")
    attach = sub.add_parser("attach", help="Bind an existing folder to a project that has none")
    attach.add_argument("project_id")
    attach.add_argument("folder", type=Path)
    sub.add_parser("projects", help="List projects")
    sub.add_parser("demo", help="Create a fictional demonstration project")
    handoff = sub.add_parser("handoff", help="Write a sourced context brief to stdout")
    handoff.add_argument("project_id")
    handoff.add_argument("--query", default="")
    handoff.add_argument("--budget", type=int, default=12000, help="Character budget (not tokens), 500 to 100000")
    imp = sub.add_parser("import", help="Import JSON/JSONL as proposals")
    imp.add_argument("project_id")
    imp.add_argument("file", type=Path)
    watch = sub.add_parser("watch", help="Watch one explicitly selected JSON/JSONL file")
    watch.add_argument("project_id")
    watch.add_argument("file", type=Path)
    watch.add_argument("--interval", type=_interval, default=3)
    export = sub.add_parser("export", help="Export readable Markdown to stdout")
    export.add_argument("project_id")
    mcp = sub.add_parser("mcp", help="Serve read/propose tools over MCP stdio (scoped to the current folder's project)")
    scope = mcp.add_mutually_exclusive_group()
    scope.add_argument("--project-folder", type=Path, help="Serve the project registered for this folder instead of the current one")
    scope.add_argument("--all-projects", action="store_true", help="Explicitly serve every project of the data folder")
    agent = sub.add_parser("agent", help="Run the permanent observer: workbench, capture and activity journal")
    agent.add_argument("--port", type=_port, default=7820)
    agent.add_argument("--interval", type=_interval, default=5.0)
    sub.add_parser("probe", help="Read-only probe of local agent sources (counts and field names only)")
    setup = sub.add_parser("setup", help="Choose the folders Filigree may observe (allowed roots)")
    setup.add_argument("--root", action="append", type=Path, default=[], help="Allowed root folder (repeatable)")
    setup.add_argument("--any-folder", action="store_true", help="Remove the restriction (v0.1 behaviour)")
    sub.add_parser("status", help="Show what Filigree has installed and is running (JSON)")
    service = sub.add_parser("service", help="Start the agent automatically at login (user scope, opt-in)")
    service.add_argument("service_action", choices=["install", "uninstall", "status"])
    service.add_argument("--dry-run", action="store_true")
    hooks = sub.add_parser("hooks", help="Opt-in agent hooks: session signals and optional context injection")
    hooks.add_argument("hooks_action", choices=["install", "uninstall", "status"])
    hooks.add_argument("--client", choices=["claude", "codex"])
    hooks.add_argument("--inject", action="store_true", help="Claude SessionStart: add the project's accepted knowledge to the session")
    hooks.add_argument("--dry-run", action="store_true")
    signal = sub.add_parser("signal", help=argparse.SUPPRESS)
    signal.add_argument("--client", choices=["claude", "codex"], required=True)
    signal.add_argument("--event", required=True)
    signal.add_argument("--session-id", default="")
    signal.add_argument("--inject", action="store_true")
    signal.add_argument("payload", nargs="?", default=None)
    activity = sub.add_parser("activity", help="Show a project's unreviewed activity journal (JSON)")
    activity.add_argument("project_id")
    activity.add_argument("--limit", type=int, default=50)
    chat = sub.add_parser("import-export", help="Import a ChatGPT or claude.ai export (.json or .zip) as proposals")
    chat.add_argument("file", type=Path)
    chat.add_argument("--project", required=True, help="Target project id (always explicit)")
    config = sub.add_parser("mcp-config", help="Print (never install) the MCP configuration for a client")
    config.add_argument("--client", choices=["claude", "codex"], required=True)
    capture = sub.add_parser("capture", help="Automatic capture of agent sessions")
    actions = capture.add_subparsers(dest="action", required=True)
    run = actions.add_parser("run", help="Run the monitor in the foreground")
    run.add_argument("--interval", type=_interval, default=3.0)
    run.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    actions.add_parser("status", help="Show capture status as JSON")
    actions.add_parser("pending", help="List unmapped sessions (keys only, no content)")
    link = actions.add_parser("link", help="Map a pending session key (native id or tap:ID) to a project")
    link.add_argument("key")
    link.add_argument("project_id")
    link.add_argument("--import-history", action="store_true", help="Also import records that predate capture for this key")
    unlink = actions.add_parser("unlink", help="Remove an explicit mapping")
    unlink.add_argument("key")
    for name in ("pause", "resume"):
        item = actions.add_parser(name, help=f"{name.capitalize()} capture (globally, or for one project)")
        item.add_argument("--project")
    for name in ("exclude", "include"):
        item = actions.add_parser(name, help=f"{name.capitalize()} a folder in automatic capture")
        item.add_argument("folder", type=Path)
    actions.add_parser("enable", help="Enable capture globally")
    actions.add_parser("disable", help="Disable capture globally")
    fallback = actions.add_parser("fallback", help="Turn the native-transcript fallback (clients launched without claude-tap) on or off")
    fallback.add_argument("mode", choices=["on", "off"])
    start = actions.add_parser("start", help="Start the monitor")
    start.add_argument("--background", action="store_true", required=True, help="Detach from this terminal")
    actions.add_parser("stop", help="Ask the running monitor to stop (cooperative stop file; no process is killed)")
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            from .server import serve as start
            start(args.data_dir, args.port, not args.no_capture)
            return
        if args.command == "mcp-config":
            print(mcp_config(args.client, args.data_dir))
            return
        if args.command == "signal":
            from .hooks import signal as record
            raise SystemExit(record(args.data_dir, args.client, args.event, args.session_id, args.inject, args.payload))
        if args.command == "agent":
            from .agent import run_agent
            run_agent(args.data_dir, args.port, interval=max(args.interval, 1.0), out=lambda line: print(line, flush=True))
            return
        if args.command in {"probe", "status", "service", "hooks"}:
            print(json.dumps(v2_command(args), ensure_ascii=False, indent=2))
            return
        store = Store(args.data_dir)
        if args.command == "capture":
            return capture_command(store, args)
        if args.command == "mcp":
            from .mcp import run, scope_for
            run(store, scope=scope_for(store, args.project_folder, args.all_projects))
            return
        if args.command == "setup":
            from .capture import Capture
            if args.any_folder == bool(args.root):
                raise ValueError("Indiquez au moins un --root DOSSIER, ou --any-folder pour lever la restriction.")
            roots = Capture(store).set_allowed_roots(None if args.any_folder else [str(root) for root in args.root])
            result = {"allowed_roots": roots, "next": ["filigree agent  (ou : filigree service install)", "filigree mcp-config --client claude|codex", "filigree hooks install --client claude --dry-run"]}
        elif args.command == "activity":
            from .server import project_activity
            store.get_project(args.project_id)
            result = project_activity(store, args.project_id, args.limit)
        elif args.command == "import-export":
            from .chat_export import parse_chat_export
            store.get_project(args.project)
            parsed = parse_chat_export(args.file)
            total = {"format": parsed["format"], "conversations": parsed["conversations"], "messages": len(parsed["events"]), "imported": 0, "duplicates": 0}
            while True:
                step = store.import_events(args.project, parsed["events"], f"export {parsed['format']} · {args.file.name}")
                total["imported"] += step["imported"]
                total["duplicates"] = step["duplicates"]
                if not step.get("remaining") or not step["imported"]:
                    break
            result = total
        elif args.command == "create":
            result = store.create_project(args.name, args.description, folder=args.folder)
        elif args.command == "attach":
            result = store.attach_folder(args.project_id, args.folder)
        elif args.command == "projects":
            result = store.list_projects()
        elif args.command == "demo":
            result = seed_demo(store)
        elif args.command == "handoff":
            if not 500 <= args.budget <= 100000:
                raise ValueError("Le budget doit être un entier entre 500 et 100000.")
            print(store.handoff(args.project_id, args.query, args.budget)["text"])
            return
        elif args.command == "export":
            print(store.export_markdown(args.project_id))
            return
        elif args.command == "import":
            if args.file.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("Maximum file size: 8 MiB")
            parse = parse_text if args.file.suffix.lower() in {".txt", ".md"} else parse_import
            try:
                text = args.file.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                raise ValueError("Le fichier n'est pas en UTF-8.") from None
            result = store.import_events(args.project_id, parse(text, args.file.name), args.file.name)
        elif args.command == "watch":
            if args.interval < 1:
                raise ValueError("Minimum watch interval: 1 second")
            store.get_project(args.project_id)
            last = None
            reported = None
            print(f"Watching {args.file.resolve()} (Ctrl+C to stop)", flush=True)
            while True:
                try:
                    stat = args.file.stat()
                    signature = (stat.st_mtime_ns, stat.st_size)
                    if signature != last:
                        last = signature  # a refused version is reported once, then ignored until the file changes
                        if stat.st_size > 8 * 1024 * 1024:
                            raise ValueError("Maximum file size: 8 MiB; rotate the selected export")
                        parse = parse_text if args.file.suffix.lower() in {".txt", ".md"} else parse_import
                        events = parse(args.file.read_text(encoding="utf-8-sig"), args.file.name)
                        result = store.import_events(args.project_id, events, args.file.name)
                        print(json.dumps({key: value for key, value in result.items() if key != "entries"}), flush=True)
                        reported = None
                except UnicodeDecodeError:
                    reported = _report_waiting("le fichier n'est pas en UTF-8", reported)
                except RecursionError:
                    reported = _report_waiting("document trop profondément imbriqué", reported)
                except (ValueError, OSError) as exc:
                    reported = _report_waiting(" ".join(str(exc).split())[:300], reported)
                time.sleep(args.interval)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except KeyboardInterrupt:
        return
    except KeyError as exc:
        print(f"Filigree: {exc.args[0] if exc.args else 'élément introuvable'}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (ValueError, OSError) as exc:
        print(f"Filigree: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except RecursionError as exc:
        print("Filigree: document trop profondément imbriqué.", file=sys.stderr)
        raise SystemExit(1) from exc
    except Exception as exc:  # unexpected shape of data: no traceback, no internals
        print(f"Filigree: opération impossible ({type(exc).__name__}).", file=sys.stderr)
        raise SystemExit(1) from exc
