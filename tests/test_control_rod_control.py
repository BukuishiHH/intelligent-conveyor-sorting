""" scripts.control_rod_control 的单元测试 """

from unittest.mock import MagicMock, call

import pytest

from scripts import control_rod_control


@pytest.fixture
def fake_client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(control_rod_control.config, "create_client", lambda: client)
    return client


def test_main_runs_conveyor_then_push_pull(fake_client, monkeypatch, capsys):
    """ 第一次 sleep 时按下 Ctrl+C, 只应下发 conveyor=run 和 first_push """
    calls = {"count": 0}

    def fake_sleep(secs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(control_rod_control.time, "sleep", fake_sleep)

    control_rod_control.main()

    assert fake_client.control_device.call_args_list == [
        call("conveyor", "run"),
        call("rod_control", "first_push"),
    ]
    fake_client.close.assert_called_once_with()
    assert "程序退出" in capsys.readouterr().out


def test_interval_constant_is_one_second():
    assert control_rod_control.ACTION_INTERVAL_SECS == 1.0
