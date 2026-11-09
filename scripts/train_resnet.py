""" ResNet 训练: 加载预训练权重, 训练 / 验证并保存模型 """

import argparse
import sys
from pathlib import Path

# 支持 `python scripts/train_resnet.py` 直接运行
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conveyor import config
from conveyor.trainer import ResNetTrainer


def parse_args(argv=None):
    """ 解析命令行参数, 默认使用 config.py 中的数据集与训练超参数 """
    parser = argparse.ArgumentParser(description="训练 ResNet 并保存最优模型")
    parser.add_argument("--data-root", default=str(config.DATASET_SPLIT_ROOT),
                        help=f"划分后的数据集目录, 默认 {config.DATASET_SPLIT_ROOT}")
    parser.add_argument("--pre-model", default=str(config.PRE_MODEL_DIR),
                        help=f"预训练权重目录, 默认 {config.PRE_MODEL_DIR}")
    parser.add_argument("--model-dir", default=str(config.MODEL_DIR),
                        help=f"模型输出目录, 默认 {config.MODEL_DIR}")
    parser.add_argument("--arch", choices=["resnet18", "resnet34", "resnet50"], default=config.MODEL_ARCH,
                        help=f"网络结构, 默认 {config.MODEL_ARCH}")
    parser.add_argument("--epochs", type=int, default=config.EPOCHS,
                        help=f"训练轮数, 默认 {config.EPOCHS}")
    parser.add_argument("--batch-size", type=int, default=config.BATCH_SIZE,
                        help=f"训练批大小, 默认 {config.BATCH_SIZE}")
    parser.add_argument("--valid-batch-size", type=int, default=config.VALID_BATCH_SIZE,
                        help=f"验证批大小, 默认 {config.VALID_BATCH_SIZE}")
    parser.add_argument("--lr", type=float, default=config.LEARNING_RATE,
                        help=f"Adam 学习率, 默认 {config.LEARNING_RATE}")
    parser.add_argument("--image-size", type=int, default=config.IMAGE_SIZE,
                        help=f"输入图片边长, 默认 {config.IMAGE_SIZE}")
    parser.add_argument("--num-workers", type=int, default=config.NUM_WORKERS,
                        help=f"DataLoader 进程数, 默认 {config.NUM_WORKERS}")
    parser.add_argument("--seed", type=int, default=config.SEED,
                        help=f"随机种子, 默认 {config.SEED}")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto",
                        help="训练设备, 默认 auto(有 GPU 用 GPU)")
    parser.add_argument("--no-pretrained", action="store_true",
                        help="不加载 pre_model 下的 ImageNet 权重, 从随机初始化开始训练")
    return parser.parse_args(argv)


def main(argv=None):
    """ 按命令行参数训练 ResNet, 保存 best.pth / last.pth 与混淆矩阵 """
    args = parse_args(argv)
    trainer = ResNetTrainer(
        data_root=args.data_root,
        pre_model_dir=args.pre_model,
        model_dir=args.model_dir,
        arch=args.arch,
        epochs=args.epochs,
        batch_size=args.batch_size,
        valid_batch_size=args.valid_batch_size,
        lr=args.lr,
        image_size=args.image_size,
        num_workers=args.num_workers,
        seed=args.seed,
        device=None if args.device == "auto" else args.device,
        pretrained=not args.no_pretrained,
    )
    result = trainer.run()
    print(f"训练完成, 验证集准确率: {result['accuracy'] * 100:.2f}%")
    print(f"最优模型: {result['best_model']}")
    print(f"混淆矩阵: {result['confusion_matrix_path']}")
    return result


if __name__ == '__main__':
    main()
