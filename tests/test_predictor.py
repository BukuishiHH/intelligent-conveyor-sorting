""" conveyor.predictor 的单元测试(CPU + 合成小图, 不依赖真实数据集与训练) """

import base64
import io

import matplotlib

matplotlib.use("Agg")               # 无界面环境下保存可视化图片

import numpy as np
import pytest
import torch
from PIL import Image

from conveyor import config
from conveyor.predictor import ResNetPredictor
from conveyor.resnet import resnet18


def make_model_file(model_path, num_classes=3):
    """ 生成随机初始化的 resnet18 权重并保存, 代替训练好的 best.pth """
    model_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(resnet18(num_classes=num_classes).state_dict(), model_path)
    return model_path


@pytest.fixture
def tiny_model(tmp_path):
    return make_model_file(tmp_path / "model" / "best.pth")


@pytest.fixture
def tiny_image(tmp_path):
    """ 80x80 的纯绿色 JPEG, 只用于验证推理流程能跑通 """
    path = tmp_path / "image.jpg"
    array = np.zeros((80, 80, 3), dtype=np.uint8)
    array[:, :, 1] = 200
    Image.fromarray(array).save(path)
    return path


def make_predictor(tiny_model, tmp_path, **kwargs):
    """ 构造 CPU + 小图 + 合成的推理器, 保证测试快速且离线 """
    options = {
        "model_path": tiny_model,
        "arch": "resnet18",
        "num_classes": 3,
        "image_size": 32,
        "class_names": list(config.DATASET_CATEGORIES),
        "device": "cpu",
        "result_path": tmp_path / "predict_result.png",
        "verbose": False,
    }
    options.update(kwargs)
    return ResNetPredictor(**options)


def test_init_defaults_follow_config():
    predictor = ResNetPredictor(device="cpu", verbose=False)

    assert predictor.model_path == config.PREDICT_MODEL
    assert predictor.arch == config.MODEL_ARCH
    assert predictor.num_classes == config.NUM_CLASSES
    assert predictor.image_size == config.IMAGE_SIZE
    assert predictor.class_names == list(config.DATASET_CATEGORIES)
    assert predictor.device.type == "cpu"
    assert predictor.result_path == config.PREDICT_RESULT
    assert predictor.model is None
    assert predictor.warmed_up is False


def test_init_rejects_mismatched_class_names():
    with pytest.raises(ValueError, match="类别名称数量"):
        ResNetPredictor(num_classes=3, class_names=["ripe", "raw"],
                        device="cpu", verbose=False)


def test_load_model_missing_file(tmp_path):
    predictor = make_predictor(tmp_path / "not-exist.pth", tmp_path)

    with pytest.raises(FileNotFoundError, match="模型文件不存在"):
        predictor.load_model()


def test_load_model_sets_eval_and_records_time(tiny_model, tmp_path):
    predictor = make_predictor(tiny_model, tmp_path)

    model = predictor.load_model()

    assert model is predictor.model
    assert model.training is False                  # eval 模式下 BN / Dropout 行为固定
    assert predictor.load_time > 0.0
    assert predictor.warmed_up is False


def test_read_image_converts_bgr_to_rgb(tiny_model, tmp_path):
    """ imdecode 得到的是 BGR, read_image 必须转成 RGB 供预处理使用 """
    image_path = tmp_path / "blue.png"
    Image.new("RGB", (40, 40), color=(0, 0, 255)).save(image_path)
    predictor = make_predictor(tiny_model, tmp_path)

    image = predictor.read_image(image_path)

    assert image.shape == (40, 40, 3)
    assert image[0, 0].tolist() == [0, 0, 255]


def test_read_image_missing_file(tiny_model, tmp_path):
    predictor = make_predictor(tiny_model, tmp_path)

    with pytest.raises(FileNotFoundError, match="图片不存在"):
        predictor.read_image(tmp_path / "not-exist.jpg")


def test_decode_image_returns_rgb(tiny_model, tmp_path):
    """ 图片字节解码后必须是 RGB, 供 ToPILImage 使用 """
    buffer = io.BytesIO()
    Image.new("RGB", (30, 20), color=(0, 0, 255)).save(buffer, format="PNG")
    predictor = make_predictor(tiny_model, tmp_path)

    image = predictor.decode_image(buffer.getvalue())

    assert image.shape == (20, 30, 3)
    assert image[0, 0].tolist() == [0, 0, 255]


def test_decode_image_rejects_invalid_bytes(tiny_model, tmp_path):
    predictor = make_predictor(tiny_model, tmp_path)

    with pytest.raises(ValueError, match="图片解码失败"):
        predictor.decode_image(b"not-an-image", source="mqtt")


def test_predict_image_accepts_rgb_array(tiny_model, tmp_path):
    """ 已解码的图片可直接推理, 不需要落盘 """
    image = np.zeros((80, 60, 3), dtype=np.uint8)
    image[:, :, 1] = 200
    predictor = make_predictor(tiny_model, tmp_path)

    result = predictor.predict_image(image)

    assert result["class_name"] in config.DATASET_CATEGORIES
    assert result["image"] is image
    assert result["input_shape"] == (1, 3, 32, 32)
    assert result["timings"]["load"] > 0.0
    assert set(result["timings"]) == {"load", "preprocess", "warmup", "inference"}
    assert result["timings"]["preprocess"] >= 0.0    # time.time() 分辨率下可能不足一个刻度
    assert result["timings"]["warmup"] > 0.0


def test_predict_base64_decodes_and_infers(tiny_model, tiny_image, tmp_path):
    """ MQTT 报文里的 base64 图片可以直接推理 """
    image_base64 = base64.b64encode(tiny_image.read_bytes()).decode("ascii")
    predictor = make_predictor(tiny_model, tmp_path)

    result = predictor.predict_base64(image_base64)

    assert result["class_name"] in config.DATASET_CATEGORIES
    assert result["image"].shape == (80, 80, 3)
    assert sum(result["probabilities"]) == pytest.approx(1.0, abs=1e-5)


def test_predict_base64_rejects_invalid_base64(tiny_model, tmp_path):
    predictor = make_predictor(tiny_model, tmp_path)

    with pytest.raises(ValueError):
        predictor.predict_base64("%%%not-base64%%%")


def test_preprocess_shape_and_device(tiny_model, tmp_path):
    predictor = make_predictor(tiny_model, tmp_path)
    image = np.zeros((80, 60, 3), dtype=np.uint8)

    batch = predictor.preprocess(image)

    assert tuple(batch.shape) == (1, 3, 32, 32)     # 补批次并 Resize 到 image_size
    assert batch.dtype == torch.float32
    assert batch.device.type == "cpu"


def test_predict_returns_class_and_probabilities(tiny_model, tiny_image, tmp_path):
    predictor = make_predictor(tiny_model, tmp_path)

    result = predictor.predict(tiny_image)

    assert result["class_name"] in config.DATASET_CATEGORIES
    assert 0 <= result["class_index"] < 3
    assert result["class_name"] == predictor.class_names[result["class_index"]]
    assert 0.0 <= result["probability"] <= 1.0
    assert result["probabilities"][result["class_index"]] == pytest.approx(result["probability"])
    assert sum(result["probabilities"]) == pytest.approx(1.0, abs=1e-5)
    assert len(result["probabilities"]) == 3
    assert result["image"].shape == (80, 80, 3)     # 保留原图尺寸, 便于可视化
    assert result["input_shape"] == (1, 3, 32, 32)
    assert set(result["timings"]) == {"load", "preprocess", "warmup", "inference"}
    assert result["timings"]["load"] > 0.0          # 首次推理会加载模型
    assert result["timings"]["warmup"] > 0.0
    assert result["timings"]["preprocess"] > 0.0
    assert result["timings"]["inference"] > 0.0
    assert predictor.model.training is False


def test_predict_reuses_loaded_model_and_warms_up_once(tiny_model, tiny_image, tmp_path):
    predictor = make_predictor(tiny_model, tmp_path)

    first = predictor.predict(tiny_image)
    second = predictor.predict(tiny_image)

    assert predictor.warmed_up is True
    assert predictor.model is not None
    assert second["timings"]["load"] == 0.0         # 模型已加载, 不再重复加载
    assert second["timings"]["warmup"] == 0.0       # 预热只做一次
    assert second["probabilities"] == pytest.approx(first["probabilities"])


def test_predict_supports_chinese_path(tiny_model, tmp_path):
    """ Windows 下 cv2.imread 不支持中文路径, read_image 必须能正常读取 """
    folder = tmp_path / "中文目录"
    folder.mkdir()
    image_path = folder / "半成熟.jpg"
    Image.fromarray(np.full((64, 64, 3), 120, dtype=np.uint8)).save(image_path)
    predictor = make_predictor(tiny_model, tmp_path)

    result = predictor.predict(image_path)

    assert result["image"].shape == (64, 64, 3)
    assert result["class_name"] in config.DATASET_CATEGORIES


def test_predict_missing_image(tiny_model, tmp_path):
    predictor = make_predictor(tiny_model, tmp_path)

    with pytest.raises(FileNotFoundError, match="图片不存在"):
        predictor.predict(tmp_path / "not-exist.jpg")


def test_save_visualization_writes_png(tiny_model, tiny_image, tmp_path):
    predictor = make_predictor(tiny_model, tmp_path)
    result = predictor.predict(tiny_image)

    path = predictor.save_visualization(result["image"], result, tmp_path / "out" / "result.png")

    assert path.is_file()
    assert path.stat().st_size > 0


def test_save_visualization_uses_default_result_path(tiny_model, tiny_image, tmp_path):
    predictor = make_predictor(tiny_model, tmp_path)
    result = predictor.predict(tiny_image)

    path = predictor.save_visualization(result["image"], result)

    assert path == tmp_path / "predict_result.png"
    assert path.is_file()
