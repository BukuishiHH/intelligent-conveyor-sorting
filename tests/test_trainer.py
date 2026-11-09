""" conveyor.trainer 的单元测试(CPU + 合成小图片, 不依赖真实数据集) """

import matplotlib

matplotlib.use("Agg")               # 无界面环境下保存混淆矩阵

from pathlib import Path

import pytest
import torch
from PIL import Image

from conveyor import config
from conveyor.resnet import PRETRAINED_WEIGHTS
from conveyor.trainer import ResNetTrainer, setup_seed


def _write_class_images(root, split, count, categories=None):
    """ 在 root/split/类别 下生成 count 张 80x80 的纯色 JPEG """
    categories = categories or config.DATASET_CATEGORIES
    for index, category in enumerate(categories):
        folder = Path(root) / split / category
        folder.mkdir(parents=True, exist_ok=True)
        for number in range(count):
            color = ((index * 70) % 256, (number * 40) % 256, 120)
            Image.new("RGB", (80, 80), color=color).save(folder / f"{number}.jpg")


@pytest.fixture
def tiny_data_root(tmp_path):
    """ 3 类, 每类 4 张训练图 + 2 张验证图 """
    root = tmp_path / "dataset_split"
    _write_class_images(root, "train", 4)
    _write_class_images(root, "valid", 2)
    return root


def make_trainer(data_root, tmp_path, **kwargs):
    """ 构造 CPU + 小图 + 不加载预训练权重的训练器, 保证测试快速且离线 """
    options = {
        "data_root": data_root,
        "pre_model_dir": tmp_path / "pre_model",
        "model_dir": tmp_path / "model",
        "arch": "resnet18",
        "epochs": 1,
        "batch_size": 2,
        "valid_batch_size": 2,
        "lr": 0.0001,
        "image_size": 32,
        "num_workers": 0,
        "seed": 0,
        "device": "cpu",
        "pretrained": False,
        "verbose": False,
    }
    options.update(kwargs)
    return ResNetTrainer(**options)


def test_setup_builds_datasets_loaders_and_model(tiny_data_root, tmp_path):
    trainer = make_trainer(tiny_data_root, tmp_path)

    trainer.setup()

    assert len(trainer.train_dataset) == 12
    assert len(trainer.valid_dataset) == 6
    assert trainer.train_dataset.classes == list(config.DATASET_CATEGORIES)
    assert trainer.valid_dataset.classes == list(config.DATASET_CATEGORIES)
    assert len(trainer.train_loader) == 6             # 12 / batch_size 2
    assert len(trainer.valid_loader) == 3             # 6 / valid_batch_size 2
    assert isinstance(trainer.train_loader.sampler, torch.utils.data.RandomSampler)
    assert isinstance(trainer.valid_loader.sampler, torch.utils.data.SequentialSampler)
    assert trainer.model.fc.out_features == 3
    assert isinstance(trainer.criterion, torch.nn.CrossEntropyLoss)
    assert isinstance(trainer.optimizer, torch.optim.Adam)


def test_setup_rejects_mismatched_classes(tiny_data_root, tmp_path):
    _write_class_images(tiny_data_root, "valid", 1, categories=["extra"])
    trainer = make_trainer(tiny_data_root, tmp_path)

    with pytest.raises(ValueError, match="类别不一致"):
        trainer.setup()


def test_build_model_loads_pretrained_path(tiny_data_root, tmp_path, monkeypatch):
    """ 开启 pretrained 时应按 config 约定的文件名加载权重, 并把 fc 换成 3 类 """
    called = {}

    def fake_load_pretrained(model, weight_path):
        called["weight_path"] = Path(weight_path)
        return True

    monkeypatch.setattr("conveyor.trainer.load_pretrained", fake_load_pretrained)
    trainer = make_trainer(tiny_data_root, tmp_path, pretrained=True)

    model = trainer.build_model(3)

    assert called["weight_path"] == (tmp_path / "pre_model" / PRETRAINED_WEIGHTS["resnet18"])
    assert model.fc.in_features == 512
    assert model.fc.out_features == 3


def test_run_trains_saves_checkpoints_and_confusion_matrix(tiny_data_root, tmp_path):
    trainer = make_trainer(tiny_data_root, tmp_path)

    result = trainer.run()

    assert len(result["history"]) == 1
    record = result["history"][0]
    for key in ("epoch", "train_loss", "train_acc", "val_loss", "val_acc"):
        assert key in record
    assert 0.0 <= result["accuracy"] <= 1.0
    assert result["confusion_matrix"].shape == (3, 3)
    assert len(result["true_labels"]) == 6
    assert len(result["predicted_labels"]) == 6
    assert Path(result["best_model"]).is_file()
    assert Path(result["last_model"]).is_file()
    assert Path(result["confusion_matrix_path"]).is_file()


def test_evaluate_returns_accuracy_for_valid_set(tiny_data_root, tmp_path):
    trainer = make_trainer(tiny_data_root, tmp_path)
    trainer.setup()

    result = trainer.evaluate(load_best=False)

    expected = sum(int(predicted == true) for predicted, true
                   in zip(result["predicted_labels"], result["true_labels"])) / 6
    assert result["accuracy"] == pytest.approx(expected)
    assert result["confusion_matrix"].sum() == 6


def test_setup_seed_is_reproducible():
    setup_seed(2024)
    first = torch.randn(4)
    setup_seed(2024)
    second = torch.randn(4)

    assert torch.equal(first, second)


def test_init_defaults_follow_config(tiny_data_root):
    trainer = ResNetTrainer(data_root=tiny_data_root, device="cpu", verbose=False)

    assert trainer.arch == config.MODEL_ARCH
    assert trainer.epochs == config.EPOCHS
    assert trainer.batch_size == config.BATCH_SIZE
    assert trainer.valid_batch_size == config.VALID_BATCH_SIZE
    assert trainer.lr == config.LEARNING_RATE
    assert trainer.image_size == config.IMAGE_SIZE
    assert trainer.num_workers == config.NUM_WORKERS
    assert trainer.seed == config.SEED
    assert trainer.device.type == "cpu"
    assert trainer.best_path == config.MODEL_DIR / "best.pth"
    assert trainer.last_path == config.MODEL_DIR / "last.pth"
