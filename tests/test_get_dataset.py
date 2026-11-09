""" scripts.get_dataset 的单元测试 """

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from conveyor import config
from scripts import get_dataset


def test_parse_args_defaults():
    args = get_dataset.parse_args([])

    assert args.host == config.BROKER
    assert args.port is None
    assert args.sub == config.TOPIC_SUB
    assert args.pub == config.TOPIC_PUB
    assert args.transport == "wss"
    assert args.folder == str(config.DATASET_RAW)


def test_parse_args_custom():
    """ 本地 broker 参数(示例代码中的 127.0.0.1:21883 / bb -> aa) """
    args = get_dataset.parse_args([
        "--host", "127.0.0.1", "--port", "21883", "--sub", "bb", "--pub", "aa",
        "--transport", "tcp", "--folder", "./dataset/raw",
    ])

    assert args.host == "127.0.0.1"
    assert args.port == 21883
    assert args.sub == "bb"
    assert args.pub == "aa"
    assert args.transport == "tcp"
    assert args.folder == "./dataset/raw"


@pytest.fixture
def fake_deps(monkeypatch):
    """ 替换 create_client 与 GetData, 只校验装配关系 """
    client = MagicMock()
    collector = MagicMock()
    captured = {}

    def fake_create_client(**kwargs):
        captured["client_kwargs"] = kwargs
        return client

    def fake_get_data(mqtt_client, folder_path):
        captured["get_data_args"] = (mqtt_client, folder_path)
        return collector

    monkeypatch.setattr(get_dataset.config, "create_client", fake_create_client)
    monkeypatch.setattr(get_dataset, "GetData", fake_get_data)
    return captured, client, collector


def test_main_wires_client_and_collector(fake_deps, monkeypatch):
    captured, client, collector = fake_deps
    monkeypatch.setattr(get_dataset, "time", SimpleNamespace(
        sleep=lambda secs: (_ for _ in ()).throw(KeyboardInterrupt)))

    get_dataset.main(["--host", "127.0.0.1", "--port", "21883", "--sub", "bb",
                      "--pub", "aa", "--transport", "tcp", "--folder", "./dataset/raw"])

    assert captured["client_kwargs"] == {
        "topic_sub": "bb",
        "topic_pub": "aa",
        "use_websocket": False,
        "broker": "127.0.0.1",
        "port": 21883,
    }
    assert captured["get_data_args"] == (client, "./dataset/raw")
    collector.close.assert_called_once_with()


def test_main_defaults_use_wss(fake_deps, monkeypatch):
    captured, _, _ = fake_deps
    monkeypatch.setattr(get_dataset, "time", SimpleNamespace(
        sleep=lambda secs: (_ for _ in ()).throw(KeyboardInterrupt)))

    get_dataset.main([])

    assert captured["client_kwargs"]["use_websocket"] is True
    assert captured["client_kwargs"]["broker"] == config.BROKER
    assert captured["client_kwargs"]["port"] is None
    assert captured["get_data_args"][1] == str(config.DATASET_RAW)


def test_main_closes_collector_on_error(fake_deps, monkeypatch):
    _, _, collector = fake_deps

    def raise_error(secs):
        raise RuntimeError("boom")

    monkeypatch.setattr(get_dataset, "time", SimpleNamespace(sleep=raise_error))

    with pytest.raises(RuntimeError):
        get_dataset.main([])

    collector.close.assert_called_once_with()
