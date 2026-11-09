""" scripts.predict_resnet 的单元测试 """

import pytest

from conveyor import config
from scripts import predict_resnet


def test_parse_args_defaults():
    args = predict_resnet.parse_args(["--image", "peach.jpg"])

    assert args.image == "peach.jpg"
    assert args.model == str(config.PREDICT_MODEL)
    assert args.arch == config.MODEL_ARCH
    assert args.image_size == config.IMAGE_SIZE
    assert args.classes == list(config.DATASET_CATEGORIES)
    assert args.output == str(config.PREDICT_RESULT)
    assert args.device == "auto"
    assert args.no_show is False


def test_parse_args_custom():
    args = predict_resnet.parse_args([
        "--image", "peach.jpg", "--model", "weights.pth", "--arch", "resnet34",
        "--image-size", "128", "--classes", "a", "b", "c", "d",
        "--output", "out.png", "--device", "cpu", "--no-show",
    ])

    assert args.image == "peach.jpg"
    assert args.model == "weights.pth"
    assert args.arch == "resnet34"
    assert args.image_size == 128
    assert args.classes == ["a", "b", "c", "d"]
    assert args.output == "out.png"
    assert args.device == "cpu"
    assert args.no_show is True


def test_parse_args_requires_image():
    with pytest.raises(SystemExit):
        predict_resnet.parse_args([])


def test_format_timings_contains_all_stages():
    result = {
        "input_shape": (1, 3, 224, 224),
        "timings": {"load": 12.34, "preprocess": 5.0, "warmup": 20.0, "inference": 8.06},
    }

    text = predict_resnet.format_timings(result)

    assert "图片尺寸: (1, 3, 224, 224)" in text
    assert "加载模型: 12.3ms" in text
    assert "预处理: 5.0ms" in text
    assert "预热: 20.0ms" in text
    assert "推理: 8.1ms" in text


def fake_result():
    """ 与 ResNetPredictor.predict 返回值结构一致的最小结果 """
    return {
        "class_index": 2,
        "class_name": "ripe",
        "probability": 0.9876,
        "probabilities": [0.001, 0.0114, 0.9876],
        "image": None,
        "input_shape": (1, 3, 96, 96),
        "timings": {"load": 1.0, "preprocess": 2.0, "warmup": 3.0, "inference": 4.0},
    }


def test_main_wires_predictor(monkeypatch, capsys):
    captured = {}

    class FakePredictor:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def predict(self, image_path):
            captured["image"] = image_path
            return fake_result()

        def save_visualization(self, image, result, save_path=None, show=False):
            captured["save_path"] = save_path
            captured["show"] = show
            return "out/result.png"

    monkeypatch.setattr(predict_resnet, "ResNetPredictor", FakePredictor)

    result = predict_resnet.main([
        "--image", "peach.jpg", "--model", "weights.pth", "--arch", "resnet50",
        "--image-size", "96", "--classes", "a", "b", "c", "--output", "out/result.png",
        "--device", "cuda",
    ])

    assert captured["kwargs"] == {
        "model_path": "weights.pth",
        "arch": "resnet50",
        "num_classes": 3,
        "image_size": 96,
        "class_names": ["a", "b", "c"],
        "device": "cuda",
        "result_path": "out/result.png",
    }
    assert captured["image"] == "peach.jpg"
    assert captured["save_path"] == "out/result.png"
    assert captured["show"] is True
    assert result["class_name"] == "ripe"
    output = capsys.readouterr().out
    assert "预测类别: ripe, 概率: 0.9876" in output
    assert "推理: 4.0ms" in output
    assert "out/result.png" in output


def test_main_auto_device_and_no_show(monkeypatch):
    captured = {}

    class FakePredictor:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def predict(self, image_path):
            return fake_result()

        def save_visualization(self, image, result, save_path=None, show=False):
            captured["show"] = show
            return save_path

    monkeypatch.setattr(predict_resnet, "ResNetPredictor", FakePredictor)

    predict_resnet.main(["--image", "peach.jpg", "--no-show"])

    assert captured["kwargs"]["device"] is None      # auto 交给推理器判断 GPU
    assert captured["kwargs"]["model_path"] == str(config.PREDICT_MODEL)
    assert captured["kwargs"]["num_classes"] == config.NUM_CLASSES
    assert captured["show"] is False
