""" 数据集采集: 接收设备上报的base64图片并保存到本地 """

import argparse
import sys
import time
from pathlib import Path

# 支持 `python scripts/get_dataset.py` 直接运行
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conveyor import config
from conveyor.dataset import GetData


def parse_args(argv=None):
    """ 解析命令行参数, 默认使用平台(wss 9002)与未成熟数据集目录 """
    parser = argparse.ArgumentParser(description="接收MQTT图像报文并保存为数据集图片")
    parser.add_argument("--host", default=config.BROKER,
                        help=f"broker地址, 默认 {config.BROKER}")
    parser.add_argument("--port", type=int, default=None,
                        help=f"broker端口, 默认 wss {config.PORT_WSS} / tcp {config.PORT_TCP}")
    parser.add_argument("--sub", default=config.TOPIC_SUB,
                        help=f"订阅主题(图像上报), 默认 {config.TOPIC_SUB}")
    parser.add_argument("--pub", default=config.TOPIC_PUB,
                        help=f"发布主题, 默认 {config.TOPIC_PUB}")
    parser.add_argument("--transport", choices=["wss", "tcp"], default="wss",
                        help="wss: WebSocket+TLS(默认); tcp: 明文MQTT")
    parser.add_argument("--folder", default=str(config.DATASET_RAW),
                        help=f"图片保存目录, 默认 {config.DATASET_RAW}")
    return parser.parse_args(argv)


def main(argv=None):
    """ 连接平台并持续接收图片, Ctrl+C 退出 """
    args = parse_args(argv)
    mqtt_client = config.create_client(topic_sub=args.sub, topic_pub=args.pub,
                                       use_websocket=(args.transport == "wss"),
                                       broker=args.host, port=args.port)
    collector = GetData(mqtt_client, args.folder)
    print(f"开始接收图片, 保存目录: {collector.folder_path}, 按 Ctrl+C 退出")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("程序退出, 关闭mqtt")
    finally:
        collector.close()


if __name__ == '__main__':
    main()
