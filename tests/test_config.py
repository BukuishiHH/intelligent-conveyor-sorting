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


def test_dataset_folders_under_project_root():
    """ 数据集目录固定在项目根下, 与运行时所在目录无关 """
    assert config.DATASET_ROOT == config.PROJECT_ROOT / "dataset"
    assert config.DATASET_RAW == config.DATASET_ROOT / "raw"
    assert config.DATASET_RIPE == config.DATASET_ROOT / "ripe"
    assert config.DATASET_HALF_RIPE == config.DATASET_ROOT / "half-ripe"


def test_image_message_constants():
    assert config.KEY_IMAGE == "image"
    assert config.IMAGE_SUFFIX == ".jpg"


def test_create_client_custom_broker_and_port(fake_mqtt_clt):
    """ 本地采集时可覆盖 broker 与端口(如 127.0.0.1:21883) """
    config.create_client(broker="127.0.0.1", port=21883, use_websocket=False)
    call = fake_mqtt_clt[0]
    assert call["args"][0] == "127.0.0.1"
    assert call["args"][1] == 21883
    assert call["kwargs"]["use_tls"] is False


def test_training_config_under_project_root():
    """ 训练目录与超参数: 权重目录、输出目录、分类数与示例一致 """
    assert config.PRE_MODEL_DIR == config.PROJECT_ROOT / "pre_model"
    assert config.MODEL_DIR == config.PROJECT_ROOT / "model"
    assert config.MODEL_ARCH in ("resnet18", "resnet34", "resnet50")
    assert config.NUM_CLASSES == len(config.DATASET_CATEGORIES) == 3
    assert config.EPOCHS > 0
    assert 0 < config.LEARNING_RATE < 1
    assert config.IMAGE_SIZE > 0

