""" scripts.recv_msg 的单元测试 """

import queue
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from scripts import recv_msg


@pytest.fixture
def fake_client(monkeypatch):
    client = MagicMock()
    client.mqtt_queue = queue.Queue()
    monkeypatch.setattr(recv_msg.config, "create_client", lambda: client)
    return client


def test_get_message_prints_reports(capsys):
    """ 队列中有消息时应打印出来, stop_event 置位后线程退出 """
    message_queue = queue.Queue()
    message_queue.put({"conveyor": "run"})
    stop_event = threading.Event()

    worker = threading.Thread(target=recv_msg.get_message,
                              args=(message_queue, stop_event), daemon=True)
    worker.start()
    time.sleep(0.3)
    stop_event.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert "收到上报:  {'conveyor': 'run'}" in capsys.readouterr().out


def test_main_sends_action_sequence(fake_client, monkeypatch, capsys):
    """ 校验下发顺序, 并用 KeyboardInterrupt 退出无限循环 """
    thread_mock = MagicMock()
    monkeypatch.setattr(recv_msg, "threading", SimpleNamespace(
        Event=threading.Event,
        Thread=lambda **kwargs: thread_mock,
    ))

    sleeps = {"count": 0}

    def fake_sleep(secs):
        sleeps["count"] += 1
        if sleeps["count"] == 4:        # 第4次 sleep 位于 while True 中
            raise KeyboardInterrupt

    monkeypatch.setattr(recv_msg.time, "sleep", fake_sleep)

    recv_msg.main()

    assert fake_client.control_device.call_args_list == [
        call("conveyor", "run"),
        call("rod_control", "first_pull"),
        call("rod_control", "first_push"),
        call("rod_control", "first_pull"),
    ]
    thread_mock.start.assert_called_once_with()
    fake_client.close.assert_called_once_with()
    assert "程序退出" in capsys.readouterr().out
