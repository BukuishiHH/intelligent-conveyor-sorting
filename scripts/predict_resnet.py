""" ResNet 单图推理: 加载训练好的权重, 输出成熟度类别 / 概率 / 各阶段耗时 """

import argparse
import sys
from pathlib import Path

# 支持 `python scripts/predict_resnet.py` 直接运行
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conveyor import config
from conveyor.predictor import ResNetPredictor


def parse_args(argv=None):
    """ 解析命令行参数, 默认加载 config.PREDICT_MODEL 指定的权重 """
    parser = argparse.ArgumentParser(description="对单张图片做 ResNet 成熟度推理")
    parser.add_argument("--image", required=True, help="待推理的图片路径")
    parser.add_argument("--model", default=str(config.PREDICT_MODEL),
                        help=f"模型权重路径, 默认 {config.PREDICT_MODEL}")
    parser.add_argument("--arch", choices=["resnet18", "resnet34", "resnet50"], default=config.MODEL_ARCH,
                        help=f"网络结构, 需与训练时一致, 默认 {config.MODEL_ARCH}")
    parser.add_argument("--image-size", type=int, default=config.IMAGE_SIZE,
                        help=f"输入图片边长, 需与训练时一致, 默认 {config.IMAGE_SIZE}")
    parser.add_argument("--classes", nargs="+", default=list(config.DATASET_CATEGORIES),
                        help=f"类别名称, 顺序需与训练时 ImageFolder 一致, 默认 {' '.join(config.DATASET_CATEGORIES)}")
    parser.add_argument("--output", default=str(config.PREDICT_RESULT),
                        help=f"可视化结果保存路径, 默认 {config.PREDICT_RESULT}")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto",
                        help="推理设备, 默认 auto(有 GPU 用 GPU)")
    parser.add_argument("--no-show", action="store_true",
                        help="只保存可视化图片, 不弹窗显示")
    return parser.parse_args(argv)


def format_timings(result):
    """ 把各阶段耗时格式化为一行文本(毫秒) """
    timings = result["timings"]
    return (f"图片尺寸: {result['input_shape']}, 加载模型: {timings['load']:.1f}ms, "
            f"预处理: {timings['preprocess']:.1f}ms, 预热: {timings['warmup']:.1f}ms, "
            f"推理: {timings['inference']:.1f}ms")


def main(argv=None):
    """ 对命令行指定的图片推理, 打印结果并保存可视化图片 """
    args = parse_args(argv)
    predictor = ResNetPredictor(
        model_path=args.model,
        arch=args.arch,
        num_classes=len(args.classes),
        image_size=args.image_size,
        class_names=args.classes,
        device=None if args.device == "auto" else args.device,
        result_path=args.output,
    )
    result = predictor.predict(args.image)
    output_path = predictor.save_visualization(result["image"], result, args.output,
                                               show=not args.no_show)
    print(f"预测类别: {result['class_name']}, 概率: {result['probability']:.4f}")
    print(format_timings(result))
    print(f"可视化结果: {output_path}")
    return result


if __name__ == '__main__':
    main()
