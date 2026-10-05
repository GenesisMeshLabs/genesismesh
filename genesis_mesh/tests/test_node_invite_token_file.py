"""The node reads its invite token from a file (v1.0.2).

start.sh passes the token in a private file so it never appears on the node's
command line, where any user on the host can read it.
"""

from __future__ import annotations

import pytest

from genesis_mesh.cli import node_cmd


class _FakeNode:
    joined_with: list[str | None] = []

    def __init__(self, *args, **kwargs):
        pass

    def join_network(self, bootstrap, validity_hours, invite_token):
        _FakeNode.joined_with.append(invite_token)

    def fetch_policy(self, bootstrap):
        pass

    def get_status(self):
        return {}


@pytest.fixture
def fake_node(monkeypatch):
    _FakeNode.joined_with = []
    monkeypatch.setattr(node_cmd, "MeshNode", _FakeNode)
    monkeypatch.setattr(node_cmd, "_load_genesis", lambda path: object())
    return _FakeNode


def test_the_invite_token_file_is_read_and_stripped(tmp_path, fake_node):
    token_file = tmp_path / "invite.token"
    token_file.write_text("tok-123\n", encoding="utf-8")
    code = node_cmd.main(["--genesis", "g.json", "--bootstrap", "http://na", "--invite-token-file", str(token_file)])
    assert code == 0
    assert fake_node.joined_with == ["tok-123"]


def test_the_command_line_token_still_works(fake_node):
    code = node_cmd.main(["--genesis", "g.json", "--bootstrap", "http://na", "--invite-token", "tok-456"])
    assert code == 0
    assert fake_node.joined_with == ["tok-456"]


def test_both_token_options_are_refused(tmp_path, fake_node):
    token_file = tmp_path / "invite.token"
    token_file.write_text("tok-123", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        node_cmd.main(["--genesis", "g.json", "--bootstrap", "http://na",
                       "--invite-token", "tok-456", "--invite-token-file", str(token_file)])
    assert exc.value.code == 2
    assert fake_node.joined_with == []
