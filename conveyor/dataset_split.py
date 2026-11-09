"""
数据集划分: 按类别随机打乱后复制为训练集 / 验证集

规则:
    - 源目录 dataset/<类别> 下的文件按类别单独打乱;
    - 训练集占比由 prop_train 决定, 验证集自动取剩余部分;
    - 只复制不移动, 源文件保持不变;
    - 目标目录结构: <target>/train/<类别> 与 <target>/valid/<类别>;
    - 默认先清空目标根目录, 避免多次划分残留旧文件造成训练/验证数据泄漏。
"""

import random
import shutil
from pathlib import Path

from conveyor import config


class SplitDataset():
    """
    把数据集按类别随机划分为训练集与验证集的类
    """

    TRAIN_NAME = "train"                    # 训练集子目录名
    VALID_NAME = "valid"                    # 验证集子目录名

    def __init__(self, source_dir=config.DATASET_ROOT, target_dir=config.DATASET_SPLIT_ROOT,
                 categories=None, prop_train=config.PROP_TRAIN, seed=config.SPLIT_SEED,
                 clean=True):
        """
        parameters:source_dir:源数据集根目录, 其下按类别分文件夹
                target_dir:划分结果根目录, 其下生成 train / valid
                categories:参与划分的类别目录名, 默认取 config.DATASET_CATEGORIES
                prop_train:训练集占比(0~1之间), 验证集自动为剩余部分
                seed:随机种子, 相同数据与种子下结果可复现; None 表示每次随机
                clean:目标根目录已存在时是否先清空, 默认清空以免残留旧文件
        """
        if not 0 < prop_train < 1:
            raise ValueError(f"prop_train 必须在 0~1 之间, 当前为 {prop_train}")
        self.source_dir = Path(source_dir)
        self.target_dir = Path(target_dir)
        self.categories = list(categories) if categories is not None else list(config.DATASET_CATEGORIES)
        self.prop_train = prop_train
        self.seed = seed
        self.clean = clean
        self.rng = random.Random(seed)              # 独立随机源, 不打乱全局 random 状态
        self.summary = {}                           # 每个类别的划分数量

    def run(self):
        """
        遍历所有类别完成划分, 并打印每个类别 train / valid 的数量

        returns:summary 字典, 形如 {"raw": {"train": 200, "valid": 51}, ...}
        """
        if not self.source_dir.is_dir():
            raise FileNotFoundError(f"源数据集目录不存在: {self.source_dir}")
        self.check_target()                         # 先校验路径安全, 再检查数据是否齐全
        missing = [c for c in self.categories if not (self.source_dir / c).is_dir()]
        if missing:                                 # 先校验再动目标目录, 避免只划分出一半
            raise FileNotFoundError(f"源数据集缺少类别目录: {', '.join(missing)}")
        self.prepare_target()
        for category in self.categories:
            counts = self.split_category(category)
            print(f"{category}: train {counts[self.TRAIN_NAME]} 张, "
                  f"valid {counts[self.VALID_NAME]} 张")
        print(f"数据集划分完成, 输出目录: {self.target_dir}")
        return self.summary

    def check_target(self):
        """ 校验目标目录不能与源目录重叠, 避免清空目标时误删源数据 """
        source = self.source_dir.resolve()
        target = self.target_dir.resolve()
        if source == target:
            raise ValueError("目标目录不能与源数据集目录相同")
        if source.is_relative_to(target):
            raise ValueError("源数据集目录不能位于目标目录内, 清空目标目录时会误删源数据")

    def prepare_target(self):
        """ 校验目标目录并创建 train / valid 下的类别子目录 """
        self.check_target()
        target = self.target_dir.resolve()
        if target.exists():
            if self.clean:
                shutil.rmtree(target)               # 清掉上次划分的残留, 避免同一张图同时出现在 train 与 valid
                print(f"{target}已清空")
            else:
                print(f"{target}已存在, 保留已有文件")
        for split_name in (self.TRAIN_NAME, self.VALID_NAME):
            for category in self.categories:
                (target / split_name / category).mkdir(parents=True, exist_ok=True)
        print(f"{target}已就绪")

    def split_category(self, category):
        """
        对单个类别随机打乱并按比例复制到 train / valid

        parameters:category:类别目录名, 如 "raw"

        returns:{"train": 训练集张数, "valid": 验证集张数}
        """
        source_category_dir = self.source_dir / category
        images = self.list_images(source_category_dir)
        if not images:
            raise ValueError(f"类别目录没有图片: {source_category_dir}")
        self.rng.shuffle(images)                    # 打乱后再切分, 避免按采集顺序产生偏斜
        split_point = int(len(images) * self.prop_train)
        train_images = images[:split_point]
        valid_images = images[split_point:]
        self.copy_images(train_images, source_category_dir,
                         self.target_dir / self.TRAIN_NAME / category)
        self.copy_images(valid_images, source_category_dir,
                         self.target_dir / self.VALID_NAME / category)
        self.summary[category] = {
            self.TRAIN_NAME: len(train_images),
            self.VALID_NAME: len(valid_images),
        }
        return self.summary[category]

    def list_images(self, folder_path):
        """ 列出目录下的文件名(只取文件, 忽略子目录), 排序后再打乱以保证结果可复现 """
        return sorted(path.name for path in Path(folder_path).iterdir() if path.is_file())

    def copy_images(self, images, source_category_dir, target_category_dir):
        """ 把图片逐个复制到目标目录(同名覆盖), 源文件保持不变 """
        for img in images:
            shutil.copy(source_category_dir / img, target_category_dir / img)
