from types import SimpleNamespace
from unittest.mock import patch

import launcher


def test_only_supported_assignments_are_claimed():
    from altruagent.official import OfficialAgentClient
    wanted = SimpleNamespace(game_type=launcher.GAME_TYPE)
    redalert = SimpleNamespace(game_type="red_alert")
    werewolf = SimpleNamespace(game_type="werewolf")
    hok = SimpleNamespace(game_type="honor_of_kings_5v5")
    other = SimpleNamespace(game_type="honor_of_kings")
    with patch.dict("os.environ", {
        launcher.KEY_ENV: "eak_live_" + "a" * 64,
        "ALTRUAGENT_CONTROL_URL": launcher.CONTROL_URL,
    }):
        client = launcher.make_official_client()
        try:
            with patch.object(OfficialAgentClient, "assignments", return_value=[other, wanted, redalert, werewolf, hok]):
                assert client.assignments() == [wanted, redalert, werewolf, hok]
        finally:
            client.close()


def test_defaults_to_both_tournament_and_testing():
    with patch.object(launcher, "load_configuration"), patch.object(launcher, "run_online", return_value=0) as run:
        assert launcher.main([]) == 0
        run.assert_called_once_with(frozenset({"tournament", "testing"}))


def test_match_flag_means_testing_only():
    with patch.object(launcher, "load_configuration"), patch.object(launcher, "run_online", return_value=0) as run:
        assert launcher.main(["--match"]) == 0
        run.assert_called_once_with(frozenset({"testing"}))


def test_key_is_redacted_from_failure(capsys):
    secret = "eak_live_" + "b" * 64
    with patch.dict("os.environ", {launcher.KEY_ENV: secret}), patch.object(
        launcher, "load_configuration", side_effect=ValueError("bad " + secret)
    ):
        assert launcher.main(["--check"]) == 1
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    assert "<redacted>" in output.err


def test_key_file_is_read_without_echo(tmp_path, monkeypatch, capsys):
    secret = "eak_live_" + "c" * 64
    path = tmp_path / "key.txt"
    path.write_text(secret + "\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(launcher.KEY_ENV, raising=False)
    monkeypatch.setenv("ALTRUAGENT_CONTROL_URL", launcher.CONTROL_URL)
    launcher.load_configuration(str(path), prompt=False)
    import os
    assert os.environ[launcher.KEY_ENV] == secret
    output = capsys.readouterr()
    assert secret not in output.out + output.err


def test_insecure_control_url_refused(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ALTRUAGENT_CONTROL_URL", "http://api.altruagent-game.com")
    try:
        launcher.load_configuration(prompt=False)
    except ValueError as error:
        assert "HTTPS" in str(error)
    else:
        raise AssertionError("Plain HTTP must not receive an agent key")


def test_offline_uses_mcp_legal_templates():
    payload = {
        "session_id": "fixture", "phase": "team_preview", "is_current_actor": True,
        "game_type": launcher.GAME_TYPE,
        "legal_actions": {"actions": [{"action_id": "select_lineup", "input": {
            "action": {"type": "select_lineup", "roster": ["a", "b", "c", "d"]}
        }}]},
    }
    def choose(state, context):
        assert state.legal_actions[0].action_id == "select_lineup"
        assert context.session_id == "fixture"
        return {"type": "select_lineup", "bring": ["a", "b", "c", "d"], "leads": ["a", "b"]}
    assert launcher._offline_action(payload, choose)["leads"] == ["a", "b"]
