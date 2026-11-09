""" scripts.split_dataset 的单元测试 """

from conveyor import config
from scripts import split_dataset


def test_parse_args_defaults():
    args = split_dataset.parse_args([])

    assert args.source == str(config.DATASET_ROOT)
    assert args.target == str(config.DATASET_SPLIT_ROOT)
    assert args.prop_train == config.PROP_TRAIN
    assert args.seed == config.SPLIT_SEED
    assert args.clean is True


def test_parse_args_custom():
    args = split_dataset.parse_args([
        "--source", "./dataset", "--target", "./out",
        "--prop-train", "0.7", "--seed", "-1", "--keep",
    ])

    assert args.source == "./dataset"
    assert args.target == "./out"
    assert args.prop_train == 0.7
    assert args.seed == -1
    assert args.clean is False


def test_main_wires_splitter(monkeypatch):
    """ main 把命令行参数映射为 SplitDataset 的构造参数并执行 """
    captured = {}

    class FakeSplitter:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def run(self):
            captured["ran"] = True

    monkeypatch.setattr(split_dataset, "SplitDataset", FakeSplitter)

    split_dataset.main(["--source", "src", "--target", "dst",
                        "--prop-train", "0.7", "--seed", "-1", "--keep"])

    assert captured["kwargs"] == {
        "source_dir": "src",
        "target_dir": "dst",
        "prop_train": 0.7,
        "seed": None,                   # -1 表示每次随机
        "clean": False,
    }
    assert captured["ran"] is True


def test_main_defaults_use_config(monkeypatch):
    captured = {}

    class FakeSplitter:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            pass

    monkeypatch.setattr(split_dataset, "SplitDataset", FakeSplitter)

    split_dataset.main([])

    assert captured["source_dir"] == str(config.DATASET_ROOT)
    assert captured["target_dir"] == str(config.DATASET_SPLIT_ROOT)
    assert captured["prop_train"] == config.PROP_TRAIN
    assert captured["seed"] == config.SPLIT_SEED
    assert captured["clean"] is True
