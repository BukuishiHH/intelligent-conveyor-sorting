""" 数据集划分: 按类别随机打乱后复制为 train / valid """

import argparse
import sys
from pathlib import Path

# 支持 `python scripts/split_dataset.py` 直接运行
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conveyor import config
from conveyor.dataset_split import SplitDataset


def parse_args(argv=None):
    """ 解析命令行参数, 默认按 config.py 里的目录与占比划分 """
    parser = argparse.ArgumentParser(description="按类别随机划分数据集为 train / valid(只复制不移动)")
    parser.add_argument("--source", default=str(config.DATASET_ROOT),
                        help=f"源数据集目录, 默认 {config.DATASET_ROOT}")
    parser.add_argument("--target", default=str(config.DATASET_SPLIT_ROOT),
                        help=f"划分结果目录, 默认 {config.DATASET_SPLIT_ROOT}")
    parser.add_argument("--prop-train", type=float, default=config.PROP_TRAIN,
                        help=f"训练集占比(0~1), 默认 {config.PROP_TRAIN}")
    parser.add_argument("--seed", type=int, default=config.SPLIT_SEED,
                        help=f"随机种子, 默认 {config.SPLIT_SEED}; 传 -1 表示每次随机")
    parser.add_argument("--keep", action="store_false", dest="clean",
                        help="保留目标目录已有文件(默认先清空, 避免残留旧文件造成数据泄漏)")
    return parser.parse_args(argv)


def main(argv=None):
    """ 按类别随机划分数据集并复制到 train / valid """
    args = parse_args(argv)
    splitter = SplitDataset(source_dir=args.source, target_dir=args.target,
                            prop_train=args.prop_train,
                            seed=None if args.seed < 0 else args.seed,
                            clean=args.clean)
    splitter.run()


if __name__ == '__main__':
    main()
