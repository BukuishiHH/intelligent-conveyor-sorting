""" 自动分拣主程序: 识别成熟度, 按光电对管位置推出对应推杆 """

import argparse
import sys
from pathlib import Path

# 支持 `python scripts/sort_conveyor.py` 直接运行
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conveyor import config
from conveyor.predictor import ResNetPredictor
from conveyor.sorter import ConveyorSorter


def parse_args(argv=None):
    """ 解析命令行参数, 默认使用平台(wss 9002)与 model/best.pth """
    parser = argparse.ArgumentParser(description="识别果实成熟度并控制推杆自动分拣")
    parser.add_argument("--host", default=config.BROKER,
                        help=f"broker地址, 默认 {config.BROKER}")
    parser.add_argument("--port", type=int, default=None,
                        help=f"broker端口, 默认 wss {config.PORT_WSS} / tcp {config.PORT_TCP}")
    parser.add_argument("--sub", default=config.TOPIC_SUB,
                        help=f"订阅主题(设备上报), 默认 {config.TOPIC_SUB}")
    parser.add_argument("--pub", default=config.TOPIC_PUB,
                        help=f"发布主题(控制指令), 默认 {config.TOPIC_PUB}")
    parser.add_argument("--transport", choices=["wss", "tcp"], default="wss",
                        help="wss: WebSocket+TLS(默认); tcp: 明文MQTT")
    parser.add_argument("--model", default=str(config.PREDICT_MODEL),
                        help=f"模型权重路径, 默认 {config.PREDICT_MODEL}")
    parser.add_argument("--arch", choices=["resnet18", "resnet34", "resnet50"], default=config.MODEL_ARCH,
                        help=f"网络结构, 需与训练时一致, 默认 {config.MODEL_ARCH}")
    parser.add_argument("--image-size", type=int, default=config.IMAGE_SIZE,
                        help=f"输入图片边长, 需与训练时一致, 默认 {config.IMAGE_SIZE}")
    parser.add_argument("--classes", nargs="+", default=list(config.DATASET_CATEGORIES),
                        help=f"类别名称, 顺序需与训练时 ImageFolder 一致, 默认 {' '.join(config.DATASET_CATEGORIES)}")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto",
                        help="推理设备, 默认 auto(有 GPU 用 GPU)")
    parser.add_argument("--switch-value", choices=["false", "true"], default="false",
                        help="光电对管触发时的上报值, 默认 false(示例设备低电平有效)")
    return parser.parse_args(argv)


def main(argv=None):
    """ 加载模型, 连接平台并循环分拣, Ctrl+C 退出 """
    args = parse_args(argv)
    predictor = ResNetPredictor(
        model_path=args.model,
        arch=args.arch,
        num_classes=len(args.classes),
        image_size=args.image_size,
        class_names=args.classes,
        device=None if args.device == "auto" else args.device,
    )
    predictor.load_model()                  # 权重缺失时立即报错, 不连接平台
    mqtt_client = config.create_client(topic_sub=args.sub, topic_pub=args.pub,
                                       use_websocket=(args.transport == "wss"),
                                       broker=args.host, port=args.port)
    sorter = None
    try:
        sorter = ConveyorSorter(mqtt_client, predictor,
                                switch_active_value=(args.switch_value == "true"))
        print("开始分拣, 按 Ctrl+C 退出")
        sorter.run()
    except KeyboardInterrupt:
        print("程序退出, 关闭mqtt")
    finally:
        if sorter is not None:
            sorter.close()                  # 取消定时器 + 停传送带 + 关 MQTT
        else:
            mqtt_client.close()


if __name__ == '__main__':
    main()