""" scripts.sort_conveyor 的单元测试 """

from unittest.mock import MagicMock

import pytest

from conveyor import config
from scripts import sort_conveyor


def test_parse_args_defaults():
    args = sort_conveyor.parse_args([])

    assert args.host == config.BROKER
    assert args.port is None
    assert args.sub == config.TOPIC_SUB
    assert args.pub == config.TOPIC_PUB
    assert args.transport == "wss"
    assert args.model == str(config.PREDICT_MODEL)
    assert args.arch == config.MODEL_ARCH
    assert args.image_size == config.IMAGE_SIZE
    assert args.classes == list(config.DATASET_CATEGORIES)
    assert args.device == "auto"
    assert args.switch_value == "false"


def test_parse_args_custom():
    """ 本地 broker 参数(示例代码中的 127.0.0.1:21883 / bb -> aa) """
    args = sort_conveyor.parse_args([
        "--host", "127.0.0.1", "--port", "21883", "--sub", "bb", "--pub", "aa",
        "--transport", "tcp", "--model", "./model/last.pth", "--arch", "resnet34",
        "--image-size", "64", "--classes", "a", "b", "--device", "cpu",
        "--switch-value", "true",
    ])

    assert args.host == "127.0.0.1"
    assert args.port == 21883
    assert args.sub == "bb"
    assert args.pub == "aa"
    assert args.transport == "tcp"
    assert args.model == "./model/last.pth"
    assert args.arch == "resnet34"
    assert args.image_size == 64
    assert args.classes == ["a", "b"]
    assert args.device == "cpu"
    assert args.switch_value == "true"


@pytest.fixture
def fake_deps(monkeypatch):
    """ 替换 create_client / ResNetPredictor / ConveyorSorter, 只校验装配关系 """
    client = MagicMock()
    predictor = MagicMock()
    sorter = MagicMock()
    captured = {}

    def fake_create_client(**kwargs):
        captured["client_kwargs"] = kwargs
        return client

    def fake_predictor(**kwargs):
        captured["predictor_kwargs"] = kwargs
        return predictor

    def fake_sorter(mqtt_client, pred, **kwargs):
        captured["sorter_args"] = (mqtt_client, pred)
        captured["sorter_kwargs"] = kwargs
        return sorter

    monkeypatch.setattr(sort_conveyor.config, "create_client", fake_create_client)
    monkeypatch.setattr(sort_conveyor, "ResNetPredictor", fake_predictor)
    monkeypatch.setattr(sort_conveyor, "ConveyorSorter", fake_sorter)
    return captured, client, predictor, sorter


def test_main_wires_client_predictor_and_sorter(fake_deps, capsys):
    captured, client, predictor, sorter = fake_deps
    sorter.run.side_effect = KeyboardInterrupt

    sort_conveyor.main(["--host", "127.0.0.1", "--port", "21883",
                        "--transport", "tcp", "--classes", "a", "b",
                        "--device", "cpu"])

    assert captured["client_kwargs"] == {
        "topic_sub": config.TOPIC_SUB,
        "topic_pub": config.TOPIC_PUB,
        "use_websocket": False,
        "broker": "127.0.0.1",
        "port": 21883,
    }
    assert captured["predictor_kwargs"] == {
        "model_path": str(config.PREDICT_MODEL),
        "arch": config.MODEL_ARCH,
        "num_classes": 2,
        "image_size": config.IMAGE_SIZE,
        "class_names": ["a", "b"],
        "device": "cpu",
    }
    predictor.load_model.assert_called_once_with()   # 启动前先校验权重, 缺失则直接报错
    assert captured["sorter_args"] == (client, predictor)
    assert captured["sorter_kwargs"] == {"switch_active_value": False}
    sorter.run.assert_called_once_with()
    sorter.close.assert_called_once_with()
    client.close.assert_not_called()                 # 由 sorter.close() 统一关闭
    assert "程序退出" in capsys.readouterr().out


def test_main_defaults_use_wss_and_auto_device(fake_deps):
    captured, _, _, sorter = fake_deps
    sorter.run.side_effect = KeyboardInterrupt

    sort_conveyor.main([])

    assert captured["client_kwargs"]["use_websocket"] is True
    assert captured["client_kwargs"]["broker"] == config.BROKER
    assert captured["client_kwargs"]["port"] is None
    assert captured["predictor_kwargs"]["device"] is None
    assert captured["predictor_kwargs"]["num_classes"] == config.NUM_CLASSES
    assert captured["sorter_kwargs"]["switch_active_value"] is False


def test_main_maps_switch_value_true(fake_deps):
    captured, _, _, sorter = fake_deps
    sorter.run.side_effect = KeyboardInterrupt

    sort_conveyor.main(["--switch-value", "true"])

    assert captured["sorter_kwargs"]["switch_active_value"] is True


def test_main_closes_sorter_on_error(fake_deps):
    _, _, _, sorter = fake_deps
    sorter.run.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        sort_conveyor.main([])

    sorter.close.assert_called_once_with()


def test_main_stops_before_connect_when_model_missing(fake_deps):
    """ 权重不存在时不连接平台, 避免设备在无模型状态下被启动 """
    captured, client, predictor, sorter = fake_deps
    predictor.load_model.side_effect = FileNotFoundError("模型文件不存在")

    with pytest.raises(FileNotFoundError):
        sort_conveyor.main([])

    assert "client_kwargs" not in captured
    assert "sorter_args" not in captured
    client.close.assert_not_called()
    sorter.run.assert_not_called()