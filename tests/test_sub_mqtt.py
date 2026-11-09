""" scripts.sub_mqtt 的单元测试 """

from types import SimpleNamespace
from unittest.mock import MagicMock

from conveyor import config
from scripts import sub_mqtt


def test_create_raw_client_uses_wss(fake_paho):
    client, captured = fake_paho("scripts.sub_mqtt", client=MagicMock())

    created = sub_mqtt.create_raw_client()

    assert created is client
    assert captured["transport"] == "websockets"
    client.ws_set_options.assert_called_once_with(path="/mqtt")
    client.tls_set.assert_called_once_with()
    assert client.on_connect is sub_mqtt.on_connect
    assert client.on_message is sub_mqtt.on_message


def test_on_connect_subscribes_device_topic(capsys):
    client = MagicMock()

    sub_mqtt.on_connect(client, None, None, SimpleNamespace(value=0), None)

    client.subscribe.assert_called_once_with(config.TOPIC_SUB, qos=1)
    assert "Connected successfully." in capsys.readouterr().out


def test_on_connect_failure_does_not_subscribe(capsys):
    client = MagicMock()

    sub_mqtt.on_connect(client, None, None, SimpleNamespace(value=5), None)

    client.subscribe.assert_not_called()
    assert "Connection failed" in capsys.readouterr().out


def test_on_message_prints_payload(capsys):
    message = SimpleNamespace(topic=config.TOPIC_SUB, payload=b'{"conveyor": "run"}')

    sub_mqtt.on_message(MagicMock(), None, message)

    out = capsys.readouterr().out
    assert 'Received message: {"conveyor": "run"}' in out
    assert f"on topic {config.TOPIC_SUB}" in out


def test_main_disconnects_on_interrupt(fake_paho, capsys):
    client, _ = fake_paho("scripts.sub_mqtt", client=MagicMock())
    client.loop_forever.side_effect = KeyboardInterrupt

    sub_mqtt.main()

    client.connect.assert_called_once_with(config.BROKER, config.PORT_WSS, config.KEEPALIVE_SECS)
    client.loop_forever.assert_called_once_with()
    client.disconnect.assert_called_once_with()
    assert "程序退出" in capsys.readouterr().out
