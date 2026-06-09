"""Shared test fixtures for HEPHAESTUS backend."""

from __future__ import annotations

import json
import pathlib
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(autouse=True)
def _isolate_registry(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermetic tests: never read the developer's real ~/.hephaestus active workspace.

    `_state_dir()` resolves to the active workspace's <repo>/.hephaestus/state when one is
    active, which would shadow tests that only patch STATE_DIR. Point the registry at an
    empty temp home so active() is None by default; tests that need a workspace replace
    `app.core.workspaces.registry` with their own (which takes precedence).
    """
    import app.core.workspaces as wsmod

    monkeypatch.setattr(wsmod, "registry", wsmod.WorkspaceRegistry(home=tmp_path / "_hephaestus_home"))


@pytest.fixture
def client() -> TestClient:
    """TestClient for FastAPI integration tests."""
    return TestClient(app)


@pytest.fixture
def tmp_state_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a temporary state directory with minimal files."""
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    # Create empty work-state.json
    state_file = state_dir / "work-state.json"
    state_file.write_text(json.dumps({"items": []}))
    # Create empty decisions.log
    (state_dir / "decisions.log").write_text("")
    return state_dir


@pytest.fixture
def state_with_items(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Temporary state dir pre-loaded with sample items."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)

    items = [
        {"id": "item-001", "title": "First task", "status": "pending", "attempts": 0},
        {"id": "item-002", "title": "Second task", "status": "done", "attempts": 1},
        {"id": "item-003", "title": "Third task", "status": "failed:verify", "attempts": 2},
    ]
    state_file = tmp_state_dir / "work-state.json"
    state_file.write_text(json.dumps({"items": items}))
    return tmp_state_dir


# ---------------------------------------------------------------------------
# Stage 3 fixtures — funnel + merge (cross-platform, no bash)
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: pathlib.Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def tmp_git_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """A bare-bones git repo with an initial commit on 'main'. Cross-platform."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "t@t.t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "README.md").write_text("hello\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "init"], repo)
    return repo


class _FakeAgentRunner:
    """Writes a scripted JSONL text event to output_path on each run().

    scripts: dict mapping lens/'arbiter-<i>'/'final' (derived from output filename stem)
    to the raw block text the agent 'emitted'. Records calls in .calls.

    R2: run() has NO session_name — each concurrent call is identified by its unique
    output_path, not a shared session.
    """

    def __init__(self, scripts: dict[str, str]) -> None:
        self.scripts = scripts
        self.calls: list[str] = []

    async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec):
        stem = pathlib.Path(output_path).name.split(".")[0]
        self.calls.append(stem)
        block = self.scripts.get(stem, self.scripts.get("*", ""))
        line = json.dumps({"type": "text", "text": block})
        pathlib.Path(output_path).write_text(line + "\n", encoding="utf-8")
        return SimpleNamespace(exit_code=0, refused=False,
                               output_path=output_path, agent_label="fake")


@pytest.fixture
def fake_agent_runner():
    return _FakeAgentRunner


def make_repo_profile(repo_path: str, *, strictness="standard", n_validators=5,
                      n_arbiters=2, with_final=True, max_revisions=2):
    """Lightweight RepoProfile-shaped object for funnel/git tests (no Stage 1 dep)."""
    review = SimpleNamespace(enabled=True, tier1_threshold=5, tier2_threshold=2,
                             max_revisions=max_revisions)
    agents = SimpleNamespace(
        primary=SimpleNamespace(provider="p", model="m", agent="primary"),  # R3 fallback source
        fallback=SimpleNamespace(provider="p", model="m", agent="fallback"),
        validators=[SimpleNamespace(provider="p", model="m", agent=f"v{i}") for i in range(n_validators)],
        arbiters=[SimpleNamespace(provider="p", model="m", agent=f"a{i}") for i in range(n_arbiters)],
        final=SimpleNamespace(provider="p", model="m", agent="f") if with_final else None,
    )
    return SimpleNamespace(
        id="ws-test", name="test", repo_path=repo_path, base_branch="main",
        remote="origin", branch_prefix="auto", agents=agents, strictness=strictness,
        review=review,
    )


@pytest.fixture
def repo_profile_factory():
    return make_repo_profile
