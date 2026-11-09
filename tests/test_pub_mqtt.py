""" scripts.pub_mqtt 的单元测试 """

from types import SimpleNamespace
from unittest.mock import MagicMock

from conveyor import config
from scripts import pub_mqtt


def test_create_raw_client_uses_wss(fake_paho):
    client, captured = fake_paho("scripts.pub_mqtt", client=MagicMock())

    created = pub_mqtt.create_raw_client()

    assert created is client
    assert captured["transport"] == "websockets"
    client.ws_set_options.assert_called_once_with(path="/mqtt")
    client.tls_set.assert_called_once_with()
    assert client.on_connect is pub_mqtt.on_connect


def test_on_connect_success(capsys):
    pub_mqtt.on_connect(MagicMock(), None, None, SimpleNamespace(value=0), None)
    assert "Connected successfully." in capsys.readouterr().out


def test_on_connect_failure(capsys):
    pub_mqtt.on_connect(MagicMock(), None, None, SimpleNamespace(value=5), None)
    assert "Connection failed" in capsys.readouterr().out


def test_main_publishes_and_closes(fake_paho, capsys):
    client, _ = fake_paho("scripts.pub_mqtt", client=MagicMock())
    info = client.publish.return_value

    pub_mqtt.main()

    client.connect.assert_called_once_with(config.BROKER, config.PORT_WSS, config.KEEPALIVE_SECS)
    client.loop_start.assert_called_once_with()
    client.publish.assert_called_once_with(config.TOPIC_PUB, pub_mqtt.message, qos=1)
    info.wait_for_publish.assert_called_once_with(timeout=config.PUBLISH_TIMEOUT_SECS)
    client.disconnect.assert_called_once_with()
    client.loop_stop.assert_called_once_with()
    assert f"已发布到 {config.TOPIC_PUB}" in capsys.readouterr().out
