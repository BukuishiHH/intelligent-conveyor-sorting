""" conveyor.sorter 的单元测试(离线替身, 不连接真实 broker) """

import queue
import threading
import time
from types import SimpleNamespace

import pytest

from conveyor import config
from conveyor.sorter import ConveyorSorter


class FakeClient:
    """ 记录下发指令的 MQTT 客户端替身 """

    def __init__(self):
        self.mqtt_queue = queue.Queue()
        self.commands = []
        self.closed = False

    def control_device(self, key, value, **kwargs):
        self.commands.append((key, value))

    def close(self):
        self.closed = True


class FakePredictor:
    """ 固定返回指定识别结果的推理器替身 """

    def __init__(self, result=None, error=None):
        self.result = result or {
            "class_name": "ripe",
            "probability": 0.9,
            "timings": {"inference": 8.0},
        }
        self.error = error
        self.calls = []

    def predict_base64(self, image_base64):
        self.calls.append(image_base64)
        if self.error is not None:
            raise self.error
        return dict(self.result)


class FakeTimer:
    """ 只记录参数、不真正执行的定时器替身 """

    def __init__(self, delay, function, args=(), kwargs=None):
        self.delay = delay
        self.function = function
        self.args = args
        self.kwargs = kwargs or {}
        self.started = False
        self.cancelled = False
        self.alive = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        pass


@pytest.fixture
def timers(monkeypatch):
    """ 把 sorter 模块里的 threading.Timer 换成 FakeTimer, 并返回创建列表 """
    created = []

    def factory(*args, **kwargs):
        timer = FakeTimer(*args, **kwargs)
        created.append(timer)
        return timer

    monkeypatch.setattr("conveyor.sorter.threading", SimpleNamespace(
        Timer=factory,
        Lock=threading.Lock,
        Event=threading.Event,
        current_thread=threading.current_thread,
    ))
    return created


def make_sorter(client=None, predictor=None, **kwargs):
    """ 构造 sorter, 默认关闭日志, 避免测试输出干扰 """
    client = client if client is not None else FakeClient()
    predictor = predictor if predictor is not None else FakePredictor()
    options = {"verbose": False}
    options.update(kwargs)
    sorter = ConveyorSorter(client, predictor, **options)
    return sorter, client, predictor


def test_init_default_rods_and_switches(timers):
    """ 默认映射与示例代码一致: first 上料, second/third/fourth 分拣 """
    sorter, _, _ = make_sorter()

    assert sorter.load_rod == config.ROD_LOAD == "first"
    assert sorter.class_rods == {
        "ripe": "second",
        "half-ripe": "third",
        "raw": "fourth",
    }
    assert sorter.switch_classes == {
        config.SWITCH_RIPE: "ripe",
        config.SWITCH_HALF_RIPE: "half-ripe",
        config.SWITCH_RAW: "raw",
    }
    assert sorter.push_secs == 1.0
    assert sorter.reload_delay == 0.2
    assert sorter.start_delay == 0.5
    assert sorter.switch_active_value is False
    assert sorter.current_class is None


def test_init_rejects_class_without_rod(timers):
    """ 对管对应的类别必须能在 class_rods 里找到推杆 """
    with pytest.raises(ValueError, match="缺少推杆映射"):
        ConveyorSorter(FakeClient(), FakePredictor(),
                       class_rods={"ripe": "second"}, verbose=False)


def test_start_runs_conveyor_and_schedules_load_rod(timers):
    sorter, client, _ = make_sorter()

    sorter.start()

    assert client.commands == [
        ("conveyor", "run"),
        ("rod_control", "all_pull"),
    ]
    assert len(timers) == 1
    assert timers[0].delay == 0.5
    assert timers[0].args == ("first",)
    assert timers[0].started is True


def test_push_pull_pushes_waits_then_pulls(timers, monkeypatch):
    sleeps = []
    monkeypatch.setattr("conveyor.sorter.time.sleep", sleeps.append)
    sorter, client, _ = make_sorter()

    sorter.push_pull("second")

    assert client.commands == [
        ("rod_control", "second_push"),
        ("rod_control", "second_pull"),
    ]
    assert sleeps == [1.0]


def test_identify_updates_current_class(timers):
    sorter, _, predictor = make_sorter()

    result = sorter.identify("image-data")

    assert predictor.calls == ["image-data"]
    assert result["class_name"] == "ripe"
    assert sorter.current_class == "ripe"


def test_identify_failure_keeps_previous_class(timers, capsys):
    """ 坏图片只跳过当前报文, 分拣循环继续使用上一次识别结果 """
    predictor = FakePredictor(error=ValueError("图片解码失败"))
    sorter, _, _ = make_sorter(predictor=predictor, verbose=True)
    sorter.current_class = "raw"

    result = sorter.identify("broken")

    assert result is None
    assert sorter.current_class == "raw"
    assert "图像识别失败" in capsys.readouterr().out


def test_switch_triggers_matching_rod_and_reload(timers):
    """ ripe 过第一个对管: 立即推 second, 0.2s 后推 first 补料 """
    sorter, _, _ = make_sorter()
    sorter.current_class = "ripe"

    sorter.handle_switch({"first_switch": False})

    assert [(timer.delay, timer.args) for timer in timers] == [
        (0.0, ("second",)),
        (0.2, ("first",)),
    ]
    assert all(timer.started for timer in timers)


def test_switch_ignored_when_class_does_not_match(timers):
    sorter, _, _ = make_sorter()
    sorter.current_class = "raw"

    sorter.handle_switch({"first_switch": False})

    assert timers == []


def test_switch_requires_configured_value(timers):
    """ 示例设备低电平有效: 默认只有 False 才算触发 """
    sorter, _, _ = make_sorter()
    sorter.current_class = "ripe"

    sorter.handle_switch({"first_switch": True})

    assert timers == []


def test_switch_active_value_is_configurable(timers):
    """ 设备若改为高电平有效, 可用 switch_active_value=True 适配 """
    sorter, _, _ = make_sorter(switch_active_value=True)
    sorter.current_class = "ripe"

    sorter.handle_switch({"first_switch": True})

    assert [(timer.delay, timer.args) for timer in timers] == [
        (0.0, ("second",)),
        (0.2, ("first",)),
    ]


def test_switch_ignores_missing_key_and_non_dict(timers):
    sorter, _, _ = make_sorter()
    sorter.current_class = "ripe"

    sorter.handle_switch({"second_switch": False})
    sorter.handle_switch({"first_switch": True})
    sorter.handle_message("not-a-dict")

    assert timers == []


def test_handle_message_routes_image_and_switch(timers):
    sorter, _, predictor = make_sorter()

    result = sorter.handle_message({"image": "image-data"})
    sorter.handle_message({"first_switch": False})

    assert result["class_name"] == "ripe"
    assert predictor.calls == ["image-data"]
    assert [(timer.delay, timer.args) for timer in timers] == [
        (0.0, ("second",)),
        (0.2, ("first",)),
    ]


def test_run_processes_messages_until_close(timers):
    """ 主循环从队列消费报文, close() 后线程退出并停传送带 """
    sorter, client, predictor = make_sorter()
    client.mqtt_queue.put({"image": "image-data"})
    client.mqtt_queue.put({"first_switch": False})
    worker = threading.Thread(target=sorter.run, daemon=True)

    worker.start()
    deadline = time.time() + 2
    while len(timers) < 3 and time.time() < deadline:   # 启动1个 + 对管2个
        time.sleep(0.01)
    sorter.close()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert predictor.calls == ["image-data"]
    assert ("conveyor", "run") in client.commands
    assert ("rod_control", "all_pull") in client.commands
    assert ("conveyor", "stop") in client.commands
    assert client.closed is True


def test_close_cancels_pending_timers_and_closes_client(timers):
    sorter, client, _ = make_sorter()
    sorter.schedule(0.0, "second")
    sorter.schedule(5.0, "first")

    sorter.close()

    assert [timer.cancelled for timer in timers] == [True, True]
    assert client.commands[-1] == ("conveyor", "stop")
    assert client.closed is True


def test_close_still_closes_client_when_stop_fails(timers, capsys):
    """ 发送停止指令失败时也要关闭 MQTT, 并提示人工确认设备状态 """
    class BrokenClient(FakeClient):
        def control_device(self, key, value, **kwargs):
            raise RuntimeError("publish failed")

    client = BrokenClient()
    sorter, _, _ = make_sorter(client=client, verbose=True)

    sorter.close()

    assert client.closed is True
    assert "停止传送带失败" in capsys.readouterr().out

