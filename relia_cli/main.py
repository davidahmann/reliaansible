"""Relia CLI entrypoint.

Commands:
  relia-cli generate --module <mod> --prompt <text>
  relia-cli lint <playbook_id>
  relia-cli test <playbook_id>
  relia-cli feedback <playbook_id>
  relia-cli export-feedback [file.csv]
  relia-cli refresh-schemas <module>...
  relia-cli doctor
  relia-cli init-starter <name>
  relia-cli telemetry <enable|disable|status>
"""
from __future__ import annotations

import logging
import subprocess
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import requests
import typer

from relia_cli.config import settings
from relia_cli.telemetry import is_enabled, record, set_enabled

# Initialize root logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = typer.Typer(help="Relia OSS CLI")

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging")
) -> None:
    """Relia CLI entrypoint allowing a global verbose flag."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        typer.echo("Verbose logging enabled")

# Ensure local directories and DB

def _init_db() -> None:
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.DATA_DIR / "db.sqlite")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playbook_id TEXT NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT,
            timestamp TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

# Telemetry Command
@app.command()
def telemetry(action: str = typer.Argument(..., help="enable | disable | status")) -> None:
    """Manage telemetry preference."""
    if action == "enable":
        set_enabled(True)
        typer.secho("✔ Telemetry enabled", fg=typer.colors.GREEN)
    elif action == "disable":
        set_enabled(False)
        typer.secho("✔ Telemetry disabled", fg=typer.colors.GREEN)
    elif action == "status":
        status = "enabled" if is_enabled() else "disabled"
        typer.echo(f"Telemetry is {status}")
    else:
        typer.secho("Expected enable/disable/status", fg=typer.colors.RED)
        raise typer.Exit(code=1)

# Generate Command
@app.command()
def generate(
    module: str = typer.Option(..., help="Ansible module (e.g., ansible.builtin.lineinfile)"),
    prompt: str = typer.Option(..., help="Natural language description of the task")
) -> None:
    """Generate an Ansible playbook using the Relia backend."""
    try:
        resp = requests.post(
            f"{settings.BACKEND_URL}/generate",
            json={"module": module, "prompt": prompt},
            timeout=15,
        )
    except requests.RequestException as exc:
        typer.secho(f"Network error: {exc}", fg=typer.colors.RED)
        record("generate_error", {"error": str(exc)})
        raise typer.Exit(1)

    if resp.status_code != 200:
        typer.secho(f"Backend error {resp.status_code}: {resp.text}", fg=typer.colors.RED)
        record("generate_error", {"status": resp.status_code})
        raise typer.Exit(2)

    payload = resp.json()
    playbook_id = payload["playbook_id"]
    yaml_text = payload["playbook_yaml"]

    settings.PLAYBOOK_DIR.mkdir(exist_ok=True)
    out_path = settings.PLAYBOOK_DIR / f"{playbook_id}.yml"
    out_path.write_text(yaml_text)

    typer.secho(f"✔ Playbook saved: {out_path}", fg=typer.colors.GREEN)
    typer.echo(yaml_text)
    record("generate", {"module": module})

# Lint & Test Commands

def _post(endpoint: str, body: dict, timeout: int = 20):
    return requests.post(f"{settings.BACKEND_URL}/{endpoint}", json=body, timeout=timeout)

@app.command()
def lint(playbook_id: str) -> None:
    """Run ansible-lint on an existing playbook."""
    resp = _post("lint", {"playbook_id": playbook_id})
    data = resp.json()
    errors = data.get("errors", [])
    if errors:
        typer.secho("✖ Lint errors:", fg=typer.colors.RED)
        typer.echo("\n".join(errors))
        record("lint", {"errors": len(errors)})
        raise typer.Exit(3)
    typer.secho("✔ No lint errors", fg=typer.colors.GREEN)
    record("lint", {"errors": 0})

@app.command()
def test(playbook_id: str) -> None:
    """Run Molecule tests against an existing playbook."""
    resp = _post("test", {"playbook_id": playbook_id}, timeout=60)
    status = resp.json().get("status")
    if status != "passed":
        typer.secho("✖ Molecule tests failed", fg=typer.colors.RED)
        record("test", {"status": status})
        raise typer.Exit(4)
    typer.secho("✔ Molecule tests passed", fg=typer.colors.GREEN)
    record("test", {"status": status})

# Feedback Command
@app.command()
def feedback(playbook_id: str) -> None:
    """Capture thumbs-up/down feedback for a playbook."""
    _init_db()
    rating_yes = typer.confirm("Was this helpful?")
    score = 1 if rating_yes else 0
    comment = typer.prompt("Optional comment", default="")
    timestamp = datetime.utcnow().isoformat()

    conn = sqlite3.connect(settings.DATA_DIR / "db.sqlite")
    conn.execute(
        "INSERT INTO feedback (playbook_id, rating, comment, timestamp) VALUES (?,?,?,?)",
        (playbook_id, score, comment, timestamp),
    )
    conn.commit()
    conn.close()
    typer.secho("Thanks for your feedback", fg=typer.colors.GREEN)
    record("feedback", {"rating": score})

# Utility Commands
@app.command()
def export_feedback(output: Path = typer.Option("feedback.csv")) -> None:
    """Export feedback to a CSV file."""
    _init_db()
    conn = sqlite3.connect(settings.DATA_DIR / "db.sqlite")
    rows = conn.execute("SELECT playbook_id,rating,comment,timestamp FROM feedback").fetchall()
    conn.close()
    with output.open("w", encoding="utf-8") as fp:
        fp.write("playbook_id,rating,comment,timestamp\n")
        for r in rows:
            fp.write(",".join(map(str, r)) + "\n")
    typer.echo(f"Exported {len(rows)} rows to {output}")
    record("export_feedback", {"count": len(rows)})

@app.command()
def refresh_schemas(modules: List[str]) -> None:
    """Refresh local JSON schemas for specified ansible.builtin modules."""
    settings.SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    for mod in modules:
        full = mod if mod.startswith("ansible.builtin.") else f"ansible.builtin.{mod}"
        typer.echo(f"Syncing schema for {full} …")
        try:
            result = subprocess.run(["ansible-doc", "-j", full], capture_output=True, text=True, check=True)
            (settings.SCHEMA_DIR / f"{full}.json").write_text(result.stdout)
            record("refresh_schema", {"module": full})
        except subprocess.CalledProcessError as exc:
            typer.secho(f"Failed: {exc}", fg=typer.colors.RED)
            record("refresh_schema_error", {"module": full})

@app.command()
def doctor() -> None:
    """Check for stale schemas and config issues."""
    warnings = False
    now = datetime.utcnow()
    for file in settings.SCHEMA_DIR.glob("*.json"):
        age = now - datetime.utcfromtimestamp(file.stat().st_mtime)
        if age > timedelta(days=settings.STALE_SCHEMA_DAYS):
            typer.secho(f"⚠ {file.name} is {age.days} days old", fg=typer.colors.YELLOW)
            warnings = True
    if warnings:
        typer.secho(f"Run 'relia-cli refresh-schemas', schemas older than {settings.STALE_SCHEMA_DAYS} days", fg=typer.colors.YELLOW)
    else:
        typer.secho("✔ Schemas are fresh", fg=typer.colors.GREEN)

@app.command()
def init_starter(name: str) -> None:
    """Scaffold a starter playbook from the curated templates."""
    available = [p.stem for p in settings.SCHEMA_DIR.parent.joinpath("starter").glob("*.yml")]
    if name not in available:
        typer.secho(f"Unknown starter {name}.", fg=typer.colors.RED)
        raise typer.Exit(1)
    dst = Path.cwd() / f"{name}.yml"
    if dst.exists():
        typer.secho("File already exists", fg=typer.colors.RED)
        raise typer.Exit(1)
    content = (settings.SCHEMA_DIR.parent.joinpath("starter") / f"{name}.yml").read_text()
    dst.write_text(content)
    typer.secho(f"Scaffolded starter: {dst}", fg=typer.colors.GREEN)

if __name__ == "__main__":
    app()