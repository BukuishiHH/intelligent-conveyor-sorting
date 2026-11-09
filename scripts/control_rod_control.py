""" 推杆控制: 传送带运行 + 推杆往复动作 """

import sys
import time
from pathlib import Path

# 支持 `python scripts/control_rod_control.py` 直接运行
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conveyor import config

ACTION_INTERVAL_SECS = 1.0      # 推杆动作间隔(秒)


def main():
    """ 连接平台, 让传送带运行并循环推杆, Ctrl+C 退出 """
    mqtt_client = config.create_client()
    try:
        mqtt_client.control_device(config.KEY_CONVEYOR, config.CONVEYOR_RUN)
        while True:
            mqtt_client.control_device(config.KEY_ROD_CONTROL, config.ROD_FIRST_PUSH)
            time.sleep(ACTION_INTERVAL_SECS)
            mqtt_client.control_device(config.KEY_ROD_CONTROL, config.ROD_FIRST_PULL)
            time.sleep(ACTION_INTERVAL_SECS)
    except KeyboardInterrupt:
        print("程序退出, 关闭mqtt")
    finally:
        mqtt_client.close()


if __name__ == '__main__':
    main()
