""" conveyor.dataset_split 的单元测试 """

import pytest

from conveyor import config
from conveyor.dataset_split import SplitDataset


def make_dataset(root, counts):
    """ 按类别批量造空文件, 文件名沿用 img0.jpg / img1.jpg ... """
    for category, count in counts.items():
        folder = root / category
        folder.mkdir(parents=True)
        for i in range(count):
            (folder / f"img{i}.jpg").write_bytes(b"image")
    return root


def test_defaults_follow_config():
    """ 默认值全部来自 config.py, 改配置即改划分行为 """
    splitter = SplitDataset()

    assert splitter.source_dir == config.DATASET_ROOT
    assert splitter.target_dir == config.DATASET_SPLIT_ROOT
    assert splitter.categories == list(config.DATASET_CATEGORIES)
    assert splitter.prop_train == config.PROP_TRAIN
    assert splitter.seed == config.SPLIT_SEED
    assert splitter.clean is True


def test_run_splits_each_category_and_keeps_source(tmp_path):
    """ 每个类别按 8:2 复制, train 与 valid 不重叠且合起来等于原数据 """
    source = make_dataset(tmp_path / "dataset", {"raw": 10, "ripe": 10, "half-ripe": 10})
    target = tmp_path / "dataset_split"

    summary = SplitDataset(source, target, prop_train=0.8, seed=42).run()

    for category in ("raw", "ripe", "half-ripe"):
        assert summary[category] == {"train": 8, "valid": 2}
        assert len(list((source / category).iterdir())) == 10       # 源文件保持原样
        train_files = {p.name for p in (target / "train" / category).iterdir()}
        valid_files = {p.name for p in (target / "valid" / category).iterdir()}
        assert len(train_files) == 8
        assert len(valid_files) == 2
        assert train_files.isdisjoint(valid_files)
        assert train_files | valid_files == {f"img{i}.jpg" for i in range(10)}
        copied = next(iter(train_files))
        assert (target / "train" / category / copied).read_bytes() == b"image"


def test_split_is_shuffled_not_head_slice(tmp_path):
    """ 划分前确实打乱: 训练集不等于按文件名顺序取前 8 张 """
    source = make_dataset(tmp_path / "dataset", {"raw": 10})
    target = tmp_path / "dataset_split"

    SplitDataset(source, target, categories=["raw"], prop_train=0.8, seed=42).run()

    train_files = {p.name for p in (target / "train" / "raw").iterdir()}
    assert train_files != {f"img{i}.jpg" for i in range(8)}


def test_same_seed_reproduces_split(tmp_path):
    """ 相同数据 + 相同种子得到相同划分 """
    source = make_dataset(tmp_path / "dataset", {"raw": 10})
    first = tmp_path / "first"
    second = tmp_path / "second"

    SplitDataset(source, first, categories=["raw"], prop_train=0.8, seed=7).run()
    SplitDataset(source, second, categories=["raw"], prop_train=0.8, seed=7).run()

    for split_name in ("train", "valid"):
        first_files = {p.name for p in (first / split_name / "raw").iterdir()}
        second_files = {p.name for p in (second / split_name / "raw").iterdir()}
        assert first_files == second_files


def test_clean_removes_stale_files(tmp_path):
    """ 默认清空目标根目录, 避免上次划分的旧文件同时残留在 train 与 valid """
    source = make_dataset(tmp_path / "dataset", {"raw": 10})
    target = tmp_path / "dataset_split"
    stale = target / "train" / "raw" / "img99.jpg"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")

    SplitDataset(source, target, categories=["raw"], prop_train=0.8, seed=1).run()

    assert not stale.exists()
    assert not (target / "train" / "raw" / "img99.jpg").exists()


def test_keep_preserves_existing_files(tmp_path):
    """ --keep: 不清空目标目录, 已有文件保留(同名文件被覆盖) """
    source = make_dataset(tmp_path / "dataset", {"raw": 10})
    target = tmp_path / "dataset_split"
    stale = target / "train" / "raw" / "img99.jpg"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")

    SplitDataset(source, target, categories=["raw"], prop_train=0.8, seed=1, clean=False).run()

    assert stale.exists()
    assert stale.read_bytes() == b"old"
    assert len(list((target / "train" / "raw").iterdir())) == 9     # 8 张新图 + 1 张旧图


def test_missing_category_raises_before_touching_target(tmp_path):
    """ 类别目录缺失时直接报错, 不会留下只划分了一半的结果 """
    source = make_dataset(tmp_path / "dataset", {"raw": 10, "ripe": 10})
    target = tmp_path / "dataset_split"

    splitter = SplitDataset(source, target, categories=("raw", "ripe", "half-ripe"))
    with pytest.raises(FileNotFoundError, match="half-ripe"):
        splitter.run()

    assert not target.exists()


def test_missing_source_raises(tmp_path):
    splitter = SplitDataset(tmp_path / "no_dataset", tmp_path / "out", categories=["raw"])

    with pytest.raises(FileNotFoundError, match="源数据集目录不存在"):
        splitter.run()


def test_empty_category_raises(tmp_path):
    source = make_dataset(tmp_path / "dataset", {"raw": 0})

    with pytest.raises(ValueError, match="没有图片"):
        SplitDataset(source, tmp_path / "out", categories=["raw"]).run()


@pytest.mark.parametrize("prop_train", [0, 1, -0.1, 1.5])
def test_invalid_prop_train_raises(prop_train):
    with pytest.raises(ValueError, match="0~1"):
        SplitDataset(prop_train=prop_train)


def test_target_must_not_be_source(tmp_path):
    source = make_dataset(tmp_path / "dataset", {"raw": 2})

    with pytest.raises(ValueError, match="不能与源数据集目录相同"):
        SplitDataset(source, source, categories=["raw"]).run()


def test_target_must_not_contain_source(tmp_path):
    """ 目标目录是源目录的父级时拒绝执行, 否则清空目标会误删源数据 """
    source = make_dataset(tmp_path / "dataset", {"raw": 2})

    with pytest.raises(ValueError, match="不能位于目标目录内"):
        SplitDataset(source, tmp_path, categories=["raw"]).run()


def test_custom_categories_only_split_selected(tmp_path):
    """ categories 可只划分指定类别 """
    source = make_dataset(tmp_path / "dataset", {"raw": 5, "ripe": 5})
    target = tmp_path / "out"

    summary = SplitDataset(source, target, categories=["ripe"], prop_train=0.6, seed=3).run()

    assert summary == {"ripe": {"train": 3, "valid": 2}}
    assert not (target / "train" / "raw").exists()
