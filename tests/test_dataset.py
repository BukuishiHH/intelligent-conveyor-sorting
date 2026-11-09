""" conveyor.dataset.GetData 的单元测试 """

import base64
import queue
import time
from types import SimpleNamespace

import pytest

from conveyor.dataset import GetData

FAKE_IMAGE_B64 = base64.b64encode(b"fake-jpeg-bytes").decode()


def wait_until(predicate, timeout=2.0):
    """ 轮询等待条件成立(子线程动作是异步的) """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class FakeBuffer:
    """ 模拟 cv2.imencode 返回的 numpy 数组 """

    def __init__(self, data=b"encoded-image"):
        self._data = data

    def tobytes(self):
        return self._data


class FakeMqtt:
    """ 只提供 GetData 需要的队列与 close() """

    def __init__(self):
        self.mqtt_queue = queue.Queue()
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


@pytest.fixture
def fake_mqtt():
    return FakeMqtt()


@pytest.fixture
def fake_cv2(monkeypatch):
    """ 用替身替换 cv2, 让图片编解码不依赖真实图像数据 """
    calls = {
        "imdecode": [],
        "imencode": [],
        "imdecode_result": "decoded-image",
        "imencode_result": (True, FakeBuffer()),
        "imdecode_error": None,
        "imencode_error": None,
    }
    namespace = SimpleNamespace(IMREAD_COLOR=1)

    def imdecode(array, flags=None):
        calls["imdecode"].append((array, flags))
        if calls["imdecode_error"] is not None:
            raise calls["imdecode_error"]
        return calls["imdecode_result"]

    def imencode(ext, image):
        calls["imencode"].append((ext, image))
        if calls["imencode_error"] is not None:
            raise calls["imencode_error"]
        return calls["imencode_result"]

    namespace.imdecode = imdecode
    namespace.imencode = imencode
    monkeypatch.setattr("conveyor.dataset.cv2", namespace)
    return calls


@pytest.fixture
def make_collector(tmp_path, fake_mqtt, fake_cv2):
    """ 构造 GetData 并在测试结束后统一关闭 """
    created = []

    def make(folder=None):
        collector = GetData(fake_mqtt, folder or tmp_path / "raw")
        created.append(collector)
        return collector

    yield make
    for collector in created:
        collector.close()


class TestMakeDir:
    def test_creates_missing_folder(self, tmp_path, fake_mqtt):
        folder = tmp_path / "dataset" / "raw"

        GetData(fake_mqtt, folder).close()

        assert folder.is_dir()

    def test_existing_folder_is_reused(self, tmp_path, fake_mqtt, capsys):
        folder = tmp_path / "raw"
        folder.mkdir()

        GetData(fake_mqtt, folder).close()

        assert "已存在" in capsys.readouterr().out


class TestNextIndex:
    def test_empty_folder_starts_at_zero(self, make_collector):
        assert make_collector().count == 0

    def test_continues_after_existing_files(self, make_collector, fake_mqtt, tmp_path):
        folder = tmp_path / "raw"
        folder.mkdir()
        (folder / "img0.jpg").write_bytes(b"")
        (folder / "img3.jpg").write_bytes(b"")
        (folder / "other.jpg").write_bytes(b"")       # 不符合规则的文件应忽略

        collector = make_collector(folder)

        assert collector.count == 4
        assert collector.save_image(FAKE_IMAGE_B64).name == "img4.jpg"


class TestSaveImage:
    def test_decodes_and_writes_file(self, make_collector, fake_cv2, capsys):
        collector = make_collector()

        path = collector.save_image(FAKE_IMAGE_B64)

        assert path is not None
        assert path.name == "img0.jpg"
        assert path.read_bytes() == b"encoded-image"
        assert fake_cv2["imencode"] == [(".jpg", "decoded-image")]
        assert fake_cv2["imdecode"][0][1] == 1        # cv2.IMREAD_COLOR
        assert "图片0已保存" in capsys.readouterr().out

    def test_index_increments_per_image(self, make_collector):
        collector = make_collector()

        first = collector.save_image(FAKE_IMAGE_B64)
        second = collector.save_image(FAKE_IMAGE_B64)

        assert (first.name, second.name) == ("img0.jpg", "img1.jpg")
        assert collector.count == 2

    def test_invalid_image_bytes_are_skipped(self, make_collector, fake_cv2, capsys):
        fake_cv2["imdecode_result"] = None
        collector = make_collector()

        assert collector.save_image(FAKE_IMAGE_B64) is None
        assert collector.count == 0
        assert fake_cv2["imencode"] == []
        assert "图片解码失败" in capsys.readouterr().out

    def test_bad_base64_returns_none(self, make_collector, capsys):
        collector = make_collector()

        assert collector.save_image("a") is None        # 长度为1, b64decode 抛错
        assert collector.count == 0
        assert "图片解码错误" in capsys.readouterr().out

    def test_encode_failure_keeps_index(self, make_collector, fake_cv2, capsys):
        fake_cv2["imencode_result"] = (False, FakeBuffer())
        collector = make_collector()

        assert collector.save_image(FAKE_IMAGE_B64) is None
        assert collector.count == 0
        assert not (collector.folder_path / "img0.jpg").exists()
        assert "图片编码失败" in capsys.readouterr().out

    def test_write_error_keeps_index(self, make_collector, fake_cv2, capsys):
        fake_cv2["imencode_error"] = OSError("disk full")
        collector = make_collector()

        assert collector.save_image(FAKE_IMAGE_B64) is None
        assert collector.count == 0
        assert "图片写入失败" in capsys.readouterr().out


class TestRecvThread:
    def test_saves_image_from_queue(self, make_collector, fake_mqtt, tmp_path):
        make_collector()

        fake_mqtt.mqtt_queue.put({"image": FAKE_IMAGE_B64})

        assert wait_until(lambda: (tmp_path / "raw" / "img0.jpg").is_file())

    def test_ignores_non_image_messages(self, make_collector, fake_mqtt, fake_cv2, tmp_path):
        collector = make_collector()

        fake_mqtt.mqtt_queue.put({"conveyor": "run"})
        time.sleep(0.2)
        assert fake_cv2["imencode"] == []
        assert collector.count == 0

        fake_mqtt.mqtt_queue.put({"image": FAKE_IMAGE_B64})
        assert wait_until(lambda: collector.count == 1)
        assert (tmp_path / "raw" / "img0.jpg").is_file()

    def test_ignores_non_dict_message(self, make_collector, fake_mqtt):
        """ 报文不是字典时线程不能崩, 后续图片仍能保存 """
        collector = make_collector()

        fake_mqtt.mqtt_queue.put("hello")
        fake_mqtt.mqtt_queue.put({"image": FAKE_IMAGE_B64})

        assert wait_until(lambda: collector.count == 1)
        assert collector.t_recv_data.is_alive()

    def test_close_stops_thread_and_client(self, tmp_path, fake_mqtt):
        collector = GetData(fake_mqtt, tmp_path / "raw")
        assert collector.t_recv_data.is_alive()

        collector.close()

        assert not collector.t_recv_data.is_alive()
        assert fake_mqtt.close_calls == 1
        assert collector.folder_path.is_dir()


class TestRealImagePipeline:
    def test_jpeg_roundtrip(self, tmp_path, fake_mqtt):
        """ 用真实 opencv 走一遍 base64 -> 保存 -> 读取, 验证整条链路 """
        cv2 = pytest.importorskip("cv2")
        np = pytest.importorskip("numpy")

        image = np.zeros((8, 12, 3), dtype=np.uint8)
        image[:, :, 1] = 255
        ok, buffer = cv2.imencode(".jpg", image)
        assert ok
        payload = base64.b64encode(buffer.tobytes()).decode()

        collector = GetData(fake_mqtt, tmp_path / "raw")
        try:
            fake_mqtt.mqtt_queue.put({"image": payload})
            assert wait_until(lambda: (tmp_path / "raw" / "img0.jpg").is_file())
        finally:
            collector.close()

        saved = cv2.imdecode(np.frombuffer((tmp_path / "raw" / "img0.jpg").read_bytes(),
                                           np.uint8), cv2.IMREAD_COLOR)
        assert saved is not None
        assert saved.shape == (8, 12, 3)

