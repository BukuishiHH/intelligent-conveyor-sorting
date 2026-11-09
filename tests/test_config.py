""" conveyor.config 的单元测试 """

import pytest

from conveyor import config


def test_connection_constants():
    """ 平台连接参数与实测一致 """
    assert config.BROKER == "mqtt.yyzlab.com.cn"
    assert config.PORT_WSS == 9002
    assert config.PORT_TCP == 1883
    assert config.WS_PATH == "/mqtt"
    assert config.KEEPALIVE_SECS == 60
    assert config.PUBLISH_TIMEOUT_SECS == 5.0


def test_topic_direction():
    """ 程序订阅设备上报(lzm1), 向设备指令主题(lzm0)发布 """
    assert config.TOPIC_SUB == "lzm1"
    assert config.TOPIC_PUB == "lzm0"


def test_command_constants():
    """ 设备指令键值 """
    assert config.KEY_CONVEYOR == "conveyor"
    assert config.KEY_ROD_CONTROL == "rod_control"
    assert config.CONVEYOR_RUN == "run"
    assert config.CONVEYOR_STOP == "stop"
    assert config.ROD_FIRST_PUSH == "first_push"
    assert config.ROD_FIRST_PULL == "first_pull"


@pytest.fixture
def fake_mqtt_clt(monkeypatch):
    """ 记录 create_client 传给 Mqtt_Clt 的参数 """
    calls = []

    class FakeMqttClt:
        def __init__(self, *args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr("conveyor.mqtt_client.Mqtt_Clt", FakeMqttClt)
    return calls


def test_create_client_defaults_to_wss(fake_mqtt_clt):
    config.create_client()
    call = fake_mqtt_clt[0]
    assert call["args"] == (config.BROKER, config.PORT_WSS,
                            config.TOPIC_SUB, config.TOPIC_PUB, config.KEEPALIVE_SECS)
    assert call["kwargs"]["use_websocket"] is True
    assert call["kwargs"]["use_tls"] is True
    assert call["kwargs"]["ws_path"] == config.WS_PATH
    assert call["kwargs"]["connect_timeout_secs"] == config.CONNECT_TIMEOUT_SECS


def test_create_client_tcp_disables_tls(fake_mqtt_clt):
    """ 走 1883 明文时 use_tls 跟随 use_websocket 自动关闭 """
    config.create_client(use_websocket=False)
    call = fake_mqtt_clt[0]
    assert call["args"][1] == config.PORT_TCP
    assert call["kwargs"]["use_websocket"] is False
    assert call["kwargs"]["use_tls"] is False


def test_create_client_custom_topics_and_id(fake_mqtt_clt):
    config.create_client(topic_sub="sub_topic", topic_pub="pub_topic", client_id="my-id")
    call = fake_mqtt_clt[0]
    assert call["args"][2] == "sub_topic"
    assert call["args"][3] == "pub_topic"
    assert call["kwargs"]["client_id"] == "my-id"
