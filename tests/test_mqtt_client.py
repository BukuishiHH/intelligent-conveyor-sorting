""" conveyor.mqtt_client.Mqtt_Clt 的单元测试 """

from types import SimpleNamespace

import pytest

from conveyor.mqtt_client import Mqtt_Clt

BROKER = "broker.example.com"
PORT = 9002
TOPIC_SUB = "lzm1"
TOPIC_PUB = "lzm0"


def build_client(**kwargs):
    """ 用平台默认形态(wss + TLS)构造客户端 """
    params = dict(use_websocket=True, use_tls=True, connect_timeout_secs=0.5)
    params.update(kwargs)
    return Mqtt_Clt(BROKER, PORT, TOPIC_SUB, TOPIC_PUB, 60, **params)


class TestInit:
    def test_websocket_and_tls_options(self, paho_factory):
        created, _ = paho_factory
        client = build_client()

        paho = created[0]
        assert paho.init_kwargs["transport"] == "websockets"
        assert paho.ws_options["path"] == "/mqtt"
        assert paho.tls_args == {"args": (), "kwargs": {}}
        assert paho.connect_calls == [(BROKER, PORT, 60)]
        assert client.connected is True

    def test_plain_tcp_without_tls(self, paho_factory):
        created, _ = paho_factory
        Mqtt_Clt(BROKER, 1883, TOPIC_SUB, TOPIC_PUB, 60,
                 use_websocket=False, use_tls=False, connect_timeout_secs=0.5)

        paho = created[0]
        assert paho.init_kwargs["transport"] == "tcp"
        assert paho.ws_options == {}
        assert paho.tls_args is None

    def test_subscribes_inside_on_connect(self, paho_factory):
        """ 订阅必须在 on_connect 里做, 断线重连后才会自动重订阅 """
        created, _ = paho_factory
        build_client()
        assert created[0].subscribe_calls == [(TOPIC_SUB, 1)]

    def test_client_id_is_unique_by_default(self, paho_factory):
        created, _ = paho_factory
        build_client()
        build_client()
        ids = [item.init_kwargs["client_id"] for item in created]
        assert all(ids)
        assert len(set(ids)) == 2

    def test_explicit_client_id(self, paho_factory):
        created, _ = paho_factory
        build_client(client_id="my-client")
        assert created[0].init_kwargs["client_id"] == "my-client"

    def test_timeout_when_no_connack(self, paho_factory):
        created, options = paho_factory
        options["auto_connack"] = False

        with pytest.raises(TimeoutError):
            build_client(connect_timeout_secs=0.05)

        paho = created[0]
        assert "disconnect" in paho.calls
        assert "loop_stop" in paho.calls

    def test_rejected_connection_raises(self, paho_factory):
        created, options = paho_factory
        options["connack_code"] = 5          # 5 = Not authorized

        with pytest.raises(ConnectionError):
            build_client()

        assert created[0].calls.count("disconnect") == 1


class TestSendJsonMsg:
    def test_publish_arguments_and_wait(self, paho_factory):
        created, _ = paho_factory
        client = build_client()

        info = client.send_json_msg({"conveyor": "stop"})

        paho = created[0]
        assert paho.publish_calls == [{
            "topic": TOPIC_PUB,
            "payload": '{"conveyor": "stop"}',
            "qos": 1,
            "retain": False,
        }]
        assert paho.message_info.wait_calls == [5.0]
        assert info is paho.message_info

    def test_no_wait_skips_confirmation(self, paho_factory):
        created, _ = paho_factory
        client = build_client()

        client.send_json_msg({"a": 1}, wait=False)

        assert created[0].message_info.wait_calls == []

    def test_custom_qos_retain_timeout(self, paho_factory):
        created, _ = paho_factory
        client = build_client()

        client.send_json_msg({"a": 1}, qos=0, retain=True, timeout=2)

        paho = created[0]
        assert paho.publish_calls[0]["qos"] == 0
        assert paho.publish_calls[0]["retain"] is True
        assert paho.message_info.wait_calls == [2]

    def test_control_device_builds_key_value(self, paho_factory, capsys):
        created, _ = paho_factory
        client = build_client()

        client.control_device("rod_control", "first_push")

        assert created[0].publish_calls[0]["payload"] == '{"rod_control": "first_push"}'
        assert "下发指令: rod_control=first_push" in capsys.readouterr().out


class TestOnMessage:
    def test_parsed_json_goes_to_queue(self, paho_factory):
        created, _ = paho_factory
        client = build_client()

        created[0].fire_message(b'{"conveyor": "run"}')

        assert client.mqtt_queue.get_nowait() == {"conveyor": "run"}

    def test_invalid_json_prints_error(self, paho_factory, capsys):
        created, _ = paho_factory
        client = build_client()

        created[0].fire_message(b"not-json")

        assert "报文解析错误" in capsys.readouterr().out
        assert client.mqtt_queue.empty()

    def test_full_queue_drops_message(self, paho_factory, capsys):
        created, _ = paho_factory
        client = build_client()
        for index in range(5):
            client.mqtt_queue.put_nowait({"index": index})

        created[0].fire_message(b'{"index": 5}')

        assert "消息队列满" in capsys.readouterr().out
        assert client.mqtt_queue.qsize() == 5


class TestDisconnectAndClose:
    def test_on_disconnect_marks_disconnected(self, paho_factory):
        created, _ = paho_factory
        client = build_client()

        client.on_disconnect(None, None, None, SimpleNamespace(value=7), None)

        assert client.connected is False

    def test_on_disconnect_prints_only_on_error(self, paho_factory, capsys):
        created, _ = paho_factory
        client = build_client()

        client.on_disconnect(None, None, None, SimpleNamespace(value=0), None)
        assert "异常断开" not in capsys.readouterr().out

        client.on_disconnect(None, None, None, SimpleNamespace(value=7), None)
        assert "异常断开" in capsys.readouterr().out

    def test_close_disconnects_before_loop_stop(self, paho_factory):
        created, _ = paho_factory
        client = build_client()
        paho = created[0]
        paho.calls.clear()

        client.close()

        assert paho.calls == ["disconnect", "loop_stop"]
        assert client.connected is False

