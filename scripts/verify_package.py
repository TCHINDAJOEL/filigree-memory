"""Install the built wheel in an isolated environment and serve its packaged UI."""
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.request import urlopen
import venv


def main():
    root = Path(__file__).resolve().parents[1]
    wheels = sorted((root / ".runtime/wheels").glob("filigree_memory-*.whl"), key=lambda path: path.stat().st_mtime_ns)
    assert wheels, "no wheel: run `python -m pip wheel . --no-deps --wheel-dir .runtime/wheels` first"
    wheel = wheels[-1]
    sources = [*(root / "filigree").glob("*.py"), *(root / "filigree/static").glob("*"), root / "pyproject.toml"]
    stale = [path.name for path in sources if path.is_file() and path.stat().st_mtime_ns > wheel.stat().st_mtime_ns]
    assert not stale, f"the newest wheel predates {stale}: rebuild it before verifying"
    with tempfile.TemporaryDirectory() as folder:
        temporary = Path(folder)
        environment = temporary / "venv"
        venv.create(environment, with_pip=True)
        python = environment / ("Scripts/python.exe" if (environment / "Scripts").exists() else "bin/python")
        subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], cwd=temporary, check=True)
        result = subprocess.run([str(python), "-m", "filigree", "--version"], cwd=temporary, capture_output=True, text=True, check=True)
        assert result.stdout.strip() == "0.1.0", result.stdout
        server = subprocess.Popen([str(python), "-m", "filigree", "--data-dir", str(temporary / "memory"), "serve", "--port", "0", "--no-capture"], cwd=temporary, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            line = server.stdout.readline()
            assert "http://" in line, line + server.stderr.read()
            url = "http://" + line.split("http://", 1)[1].strip()
            with urlopen(url, timeout=10) as response:
                assert b"Filigree" in response.read()
            with urlopen(url + "/app.js", timeout=10) as response:
                script = response.read()
                assert b"handleSubmit" in script
                assert "Le texte saisi dans l’import".encode() in script, "packaged UI predates the import-draft confirmation"
            capture = subprocess.run([str(python), "-c", "import filigree.capture as c, inspect; print('hold-fallback' in inspect.getsource(c))"], cwd=temporary, capture_output=True, text=True, check=True)
            assert capture.stdout.strip() == "True", "packaged capture predates the fallback-only hold"
            with urlopen(url + "/api/bootstrap", timeout=10) as response:
                assert json.load(response)["version"] == "0.1.0"
            print("PASS: isolated wheel install, CLI version, packaged HTML/JS, local bootstrap")
        finally:
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    main()
