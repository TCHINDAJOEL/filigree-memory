"""Optional automatic start of `filigree agent` at login, per user, without administrator rights (ADR-0003).

`plan()` is pure and fully testable; `apply()`/`remove()`/`status()` act only through an injectable runner, so tests
never touch the real registry, the real HOME or systemd. Nothing is installed unless the user runs
`filigree service install`.
"""

from __future__ import annotations

from pathlib import Path
import platform
import subprocess
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Filigree Agent"
LABEL = "dev.filigree.agent"


def _launcher(python: str, checkout) -> list[str]:
    """Interpreter arguments that start Filigree, from an installed package or a source checkout."""
    if checkout:
        return [python, "-c", f"import sys;sys.path.insert(0,{str(checkout)!r});from filigree.cli import main;main()"]
    return [python, "-m", "filigree"]


def _quote_windows(argument: str) -> str:
    return '"' + argument.replace('"', '\\"') + '"' if any(ch in argument for ch in ' \t"') or not argument else argument


def plan(system: str, python: str, data_dir, home, env=None, checkout=None) -> dict:
    """What `install` would write, for `system` in {Windows, Darwin, Linux}. Pure: no I/O."""
    data_dir, home, env = str(Path(data_dir)), Path(home), dict(env or {})
    if system == "Windows":
        pythonw = str(Path(python).with_name("pythonw.exe")) if Path(python).name.lower() == "python.exe" else python
        command = " ".join(_quote_windows(part) for part in [*_launcher(pythonw, checkout), "--data-dir", data_dir, "agent"])
        return {"system": system, "kind": "registry", "key": RUN_KEY, "name": VALUE_NAME, "command": command, "description": f"HKCU\\{RUN_KEY} → « {VALUE_NAME} »"}
    arguments = [*_launcher(python, checkout), "--data-dir", data_dir, "agent"]
    if system == "Darwin":
        path = home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        from xml.sax.saxutils import escape
        items = "\n".join(f"    <string>{escape(argument)}</string>" for argument in arguments)
        text = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
                f"<plist version=\"1.0\">\n<dict>\n  <key>Label</key>\n  <string>{LABEL}</string>\n  <key>ProgramArguments</key>\n  <array>\n{items}\n  </array>\n"
                "  <key>RunAtLoad</key>\n  <true/>\n  <key>KeepAlive</key>\n  <dict>\n    <key>SuccessfulExit</key>\n    <false/>\n  </dict>\n</dict>\n</plist>\n")
        return {"system": system, "kind": "file", "path": str(path), "text": text, "after": [["launchctl", "load", "-w", str(path)]], "before_remove": [["launchctl", "unload", "-w", str(path)]], "description": str(path)}
    if system == "Linux":
        config = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
        path = config / "systemd" / "user" / "filigree-agent.service"
        quoted = " ".join('"' + argument.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"' for argument in arguments)
        text = f"[Unit]\nDescription=Filigree local project memory agent\n\n[Service]\nExecStart={quoted}\nRestart=on-failure\n\n[Install]\nWantedBy=default.target\n"
        return {"system": system, "kind": "file", "path": str(path), "text": text,
                "after": [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", "filigree-agent.service"]],
                "before_remove": [["systemctl", "--user", "disable", "--now", "filigree-agent.service"]], "description": str(path)}
    raise ValueError(f"Démarrage automatique non pris en charge sur {system}.")


class SystemRunner:
    """Real side effects. Used only by the CLI."""

    def write(self, path: str, text: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding="utf-8")

    def read(self, path: str) -> str | None:
        try:
            return Path(path).read_text(encoding="utf-8")
        except OSError:
            return None

    def delete(self, path: str):
        Path(path).unlink(missing_ok=True)

    def run(self, command: list[str]):
        subprocess.run(command, check=False, capture_output=True, timeout=30)

    def reg_get(self, key: str, name: str) -> str | None:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                return winreg.QueryValueEx(handle, name)[0]
        except OSError:
            return None

    def reg_set(self, key: str, name: str, value: str):
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
            winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)

    def reg_delete(self, key: str, name: str):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as handle:
                winreg.DeleteValue(handle, name)
        except FileNotFoundError:
            pass


def apply(planned: dict, runner) -> dict:
    if planned["kind"] == "registry":
        runner.reg_set(planned["key"], planned["name"], planned["command"])
    else:
        runner.write(planned["path"], planned["text"])
        for command in planned.get("after", []):
            runner.run(command)
    return {"installed": planned["description"]}


def remove(planned: dict, runner) -> dict:
    if planned["kind"] == "registry":
        runner.reg_delete(planned["key"], planned["name"])
    else:
        if runner.read(planned["path"]) is not None:
            for command in planned.get("before_remove", []):
                runner.run(command)
        runner.delete(planned["path"])
    return {"removed": planned["description"]}


def status(planned: dict, runner) -> dict:
    current = runner.reg_get(planned["key"], planned["name"]) if planned["kind"] == "registry" else runner.read(planned["path"])
    expected = planned["command"] if planned["kind"] == "registry" else planned["text"]
    return {"installed": current is not None, "up_to_date": current == expected, "location": planned["description"]}


def current_plan(data_dir, env=None, home=None) -> dict:
    from .cli import _source_checkout
    return plan(platform.system(), sys.executable or "python", Path(data_dir).expanduser().resolve(), home or Path.home(), env, _source_checkout())
