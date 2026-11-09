""" scripts.train_resnet 的单元测试 """

from conveyor import config
from scripts import train_resnet


def test_parse_args_defaults():
    args = train_resnet.parse_args([])

    assert args.data_root == str(config.DATASET_SPLIT_ROOT)
    assert args.pre_model == str(config.PRE_MODEL_DIR)
    assert args.model_dir == str(config.MODEL_DIR)
    assert args.arch == config.MODEL_ARCH
    assert args.epochs == config.EPOCHS
    assert args.batch_size == config.BATCH_SIZE
    assert args.valid_batch_size == config.VALID_BATCH_SIZE
    assert args.lr == config.LEARNING_RATE
    assert args.image_size == config.IMAGE_SIZE
    assert args.num_workers == config.NUM_WORKERS
    assert args.seed == config.SEED
    assert args.device == "auto"
    assert args.no_pretrained is False


def test_parse_args_custom():
    args = train_resnet.parse_args([
        "--data-root", "./data", "--pre-model", "./weights", "--model-dir", "./out",
        "--arch", "resnet34", "--epochs", "3", "--batch-size", "8",
        "--valid-batch-size", "2", "--lr", "0.001", "--image-size", "128",
        "--num-workers", "2", "--seed", "7", "--device", "cpu", "--no-pretrained",
    ])

    assert args.data_root == "./data"
    assert args.pre_model == "./weights"
    assert args.model_dir == "./out"
    assert args.arch == "resnet34"
    assert args.epochs == 3
    assert args.batch_size == 8
    assert args.valid_batch_size == 2
    assert args.lr == 0.001
    assert args.image_size == 128
    assert args.num_workers == 2
    assert args.seed == 7
    assert args.device == "cpu"
    assert args.no_pretrained is True


def test_main_wires_trainer(monkeypatch, capsys):
    """ main 把命令行参数映射为 ResNetTrainer 的构造参数并执行 """
    captured = {}

    class FakeTrainer:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def run(self):
            captured["ran"] = True
            return {
                "accuracy": 0.75,
                "best_model": "model/best.pth",
                "confusion_matrix_path": "model/confusion_matrix.png",
            }

    monkeypatch.setattr(train_resnet, "ResNetTrainer", FakeTrainer)

    result = train_resnet.main([
        "--data-root", "data", "--pre-model", "weights", "--model-dir", "out",
        "--arch", "resnet50", "--epochs", "2", "--batch-size", "4",
        "--valid-batch-size", "1", "--lr", "0.01", "--image-size", "96",
        "--num-workers", "1", "--seed", "3", "--device", "cuda", "--no-pretrained",
    ])

    assert captured["kwargs"] == {
        "data_root": "data",
        "pre_model_dir": "weights",
        "model_dir": "out",
        "arch": "resnet50",
        "epochs": 2,
        "batch_size": 4,
        "valid_batch_size": 1,
        "lr": 0.01,
        "image_size": 96,
        "num_workers": 1,
        "seed": 3,
        "device": "cuda",
        "pretrained": False,
    }
    assert captured["ran"] is True
    assert result["accuracy"] == 0.75
    output = capsys.readouterr().out
    assert "75.00%" in output
    assert "model/best.pth" in output


def test_main_auto_device_and_pretrained_default(monkeypatch):
    captured = {}

    class FakeTrainer:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            return {"accuracy": 0.0, "best_model": "best.pth", "confusion_matrix_path": "cm.png"}

    monkeypatch.setattr(train_resnet, "ResNetTrainer", FakeTrainer)

    train_resnet.main([])

    assert captured["device"] is None            # auto 交给训练器判断 GPU
    assert captured["pretrained"] is True
    assert captured["data_root"] == str(config.DATASET_SPLIT_ROOT)
    assert captured["model_dir"] == str(config.MODEL_DIR)
