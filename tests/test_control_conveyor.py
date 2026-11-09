""" scripts.control_conveyor 的单元测试 """

from unittest.mock import MagicMock

import pytest

from scripts import control_conveyor


@pytest.fixture
def fake_client(monkeypatch):
    """ 替换 create_client, 返回可断言的假客户端 """
    info = MagicMock()
    info.is_published.return_value = True
    client = MagicMock()
    client.control_device.return_value = info
    monkeypatch.setattr(control_conveyor.config, "create_client", lambda: client)
    return client, info


def test_main_sends_stop_and_closes(fake_client, capsys):
    client, _ = fake_client

    control_conveyor.main()

    client.control_device.assert_called_once_with("conveyor", "stop")
    client.close.assert_called_once_with()
    out = capsys.readouterr().out
    assert "指令已确认送达broker" in out
    assert out.strip().endswith("结束")


def test_main_reports_unconfirmed_publish(fake_client, capsys):
    _, info = fake_client
    info.is_published.return_value = False

    control_conveyor.main()

    assert "指令未被broker确认" in capsys.readouterr().out


def test_main_closes_connection_on_error(fake_client):
    client, _ = fake_client
    client.control_device.side_effect = RuntimeError("publish failed")

    with pytest.raises(RuntimeError):
        control_conveyor.main()

    client.close.assert_called_once_with()
