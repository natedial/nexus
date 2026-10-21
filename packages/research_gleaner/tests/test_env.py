import os

from research_gleaner import env


def test_environment_precedence(monkeypatch, tmp_path):
    repo = tmp_path / "nexus"
    package = repo / "packages" / "research_gleaner"
    module = package / "src" / "research_gleaner" / "env.py"
    module.parent.mkdir(parents=True)
    (repo / ".env").write_text("SHARED=root\nROOT_ONLY=yes\n")
    (package / ".env").write_text("SHARED=package\nPACKAGE_ONLY=yes\n")

    monkeypatch.setattr(env, "Path", lambda _value: module)
    monkeypatch.setenv("SHARED", "process")
    monkeypatch.delenv("ROOT_ONLY", raising=False)
    monkeypatch.delenv("PACKAGE_ONLY", raising=False)

    env.load_environment()

    assert os.environ["SHARED"] == "process"
    assert os.environ["ROOT_ONLY"] == "yes"
    assert os.environ["PACKAGE_ONLY"] == "yes"
