"""
pytest 公共配置与测试替身

所有测试都在离线环境下运行, 不会真的连接平台 broker:
    - FakePahoClient 模拟 paho.mqtt.client.Client 的最小行为;
    - paho_factory 把 conveyor.mqtt_client 里的 mqtt.Client 替换成工厂函数;
    - 让 loop_start() 立即回调 on_connect, 模拟 broker 返回 CONNACK。
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class FakeMessageInfo:
    """ 模拟 paho 的 MQTTMessageInfo """

    def __init__(self, published=True, rc=0):
        self._published = published
        self.rc = rc
        self.wait_calls = []

    def wait_for_publish(self, timeout=None):
        self.wait_calls.append(timeout)
        if not self._published:
            raise RuntimeError("Message publish failed")

    def is_published(self):
        return self._published


class FakePahoClient:
    """ 模拟 paho.mqtt.client.Client 的最小实现, 用于离线单元测试 """

    def __init__(self, callback_api_version=None, client_id=None, transport="tcp"):
        self.init_kwargs = {
            "callback_api_version": callback_api_version,
            "client_id": client_id,
            "transport": transport,
        }
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None
        self.ws_options = {}
        self.tls_args = None
        self.connect_calls = []
        self.subscribe_calls = []
        self.publish_calls = []
        self.calls = []                 # 记录方法调用顺序
        self.auto_connack = True        # loop_start 时是否自动回调 on_connect
        self.connack_code = 0           # CONNACK 返回码
        self.message_info = FakeMessageInfo()

    # ---------------- paho 客户端接口 ----------------
    def ws_set_options(self, path=None, **kwargs):
        self.ws_options["path"] = path
        self.ws_options.update(kwargs)

    def tls_set(self, *args, **kwargs):
        self.tls_args = {"args": args, "kwargs": kwargs}

    def connect(self, host, port, keepalive=60, *args, **kwargs):
        self.connect_calls.append((host, port, keepalive))
        self.calls.append("connect")
        return 0

    def loop_start(self):
        self.calls.append("loop_start")
        if self.auto_connack:
            self.fire_connack(self.connack_code)

    def loop_stop(self):
        self.calls.append("loop_stop")

    def disconnect(self):
        self.calls.append("disconnect")
        if self.on_disconnect is not None:
            self.on_disconnect(self, None, {}, SimpleNamespace(value=0), None)
        return 0

    def subscribe(self, topic, qos=0, *args, **kwargs):
        self.subscribe_calls.append((topic, qos))
        return (0, 1)

    def publish(self, topic, payload=None, qos=0, retain=False, *args, **kwargs):
        self.publish_calls.append({
            "topic": topic,
            "payload": payload,
            "qos": qos,
            "retain": retain,
        })
        return self.message_info

    # ---------------- 测试辅助 ----------------
    def fire_connack(self, code=0):
        """ 模拟 broker 返回 CONNACK """
        self.on_connect(self, None, {}, SimpleNamespace(value=code), None)

    def fire_message(self, payload, topic="lzm1"):
        """ 模拟收到一条消息 """
        self.on_message(self, None, SimpleNamespace(topic=topic, payload=payload))


@pytest.fixture
def paho_factory(monkeypatch):
    """
    把 conveyor.mqtt_client 中的 mqtt.Client 替换为工厂函数

    returns:(created, options)
            created: 构造出来的 FakePahoClient 列表
            options: 构造前可修改 auto_connack / connack_code
    """
    created = []
    options = {"auto_connack": True, "connack_code": 0}

    def factory(*args, **kwargs):
        client = FakePahoClient(*args, **kwargs)
        client.auto_connack = options["auto_connack"]
        client.connack_code = options["connack_code"]
        created.append(client)
        return client

    monkeypatch.setattr("conveyor.mqtt_client.mqtt.Client", factory)
    return created, options


@pytest.fixture
def fake_paho(monkeypatch):
    """
    把脚本模块里的 mqtt.Client 替换为指定 Fake 客户端

    用法: client, captured = fake_paho("scripts.pub_mqtt")
    """
    holders = {}

    def make(module_path, client=None):
        fake = client or FakePahoClient()
        captured = {}

        def factory(*args, **kwargs):
            captured.update(kwargs)
            return fake

        monkeypatch.setattr(f"{module_path}.mqtt.Client", factory)
        holders[module_path] = fake
        return fake, captured

    return make
