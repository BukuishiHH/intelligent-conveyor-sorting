""" 接收设备上报 + 演示下发一串动作 """

import queue
import sys
import threading
import time
from pathlib import Path

# 支持 `python scripts/recv_msg.py` 直接运行
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conveyor import config

ACTION_INTERVAL_SECS = 1.0      # 动作间隔(秒)


def get_message(mqtt_queue, stop_event=None):
    """
    线程函数: 从队列中取出设备上报并打印

    parameters:mqtt_queue:Mqtt_Clt.mqtt_queue, 存放已解析的消息
            stop_event:threading.Event, 置位后退出循环(为None时一直运行)
    """
    while stop_event is None or not stop_event.is_set():
        try:
            msg = mqtt_queue.get(timeout=0.5)
            print("收到上报: ", msg)
        except queue.Empty:
            continue


def main():
    """ 连接平台, 边接收上报边下发一串动作, Ctrl+C 退出 """
    mqtt_client = config.create_client()
    stop_event = threading.Event()
    t_get_msg = threading.Thread(target=get_message,
                                 args=[mqtt_client.mqtt_queue, stop_event], daemon=True)
    t_get_msg.start()

    try:
        mqtt_client.control_device(config.KEY_CONVEYOR, config.CONVEYOR_RUN)
        time.sleep(ACTION_INTERVAL_SECS)
        mqtt_client.control_device(config.KEY_ROD_CONTROL, config.ROD_FIRST_PULL)
        time.sleep(ACTION_INTERVAL_SECS)
        mqtt_client.control_device(config.KEY_ROD_CONTROL, config.ROD_FIRST_PUSH)
        time.sleep(ACTION_INTERVAL_SECS)
        mqtt_client.control_device(config.KEY_ROD_CONTROL, config.ROD_FIRST_PULL)

        # 主线程持续运行，防止程序退出
        while True:
            time.sleep(ACTION_INTERVAL_SECS)
    except KeyboardInterrupt:
        print("程序退出, 关闭mqtt")
    finally:
        stop_event.set()
        mqtt_client.close()


if __name__ == '__main__':
    main()
