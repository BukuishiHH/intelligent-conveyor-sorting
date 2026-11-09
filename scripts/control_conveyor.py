""" 传送带控制: 下发停止指令 """

import sys
from pathlib import Path

# 支持 `python scripts/control_conveyor.py` 直接运行(把项目根目录加入模块搜索路径)
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conveyor import config


def main():
    """ 连接平台, 下发传送带停止指令, 并确认是否送达 """
    mqtt_client = config.create_client()
    try:
        info = mqtt_client.control_device(config.KEY_CONVEYOR, config.CONVEYOR_STOP)
        if info.is_published():
            print("指令已确认送达broker")
        else:
            print("指令未被broker确认, 请检查网络")
    finally:
        mqtt_client.close()
    print("结束")


if __name__ == '__main__':
    main()
