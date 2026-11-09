""" MQTT 订阅示例: 直接用 paho 订阅设备上报 """

import sys
from pathlib import Path

# 支持 `python scripts/sub_mqtt.py` 直接运行
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import paho.mqtt.client as mqtt

from conveyor import config

topic = config.TOPIC_SUB


def on_connect(client, userdata, connect_flags, reason_code, properties):
    """ 连接回调: 连接成功后订阅设备上报主题 """
    if getattr(reason_code, "value", reason_code) == 0:
        print("Connected successfully.")
        client.subscribe(topic, qos=1)
    else:
        print(f"Connection failed, reason_code={reason_code}")


def on_message(client, userdata, msg):
    """ 消息回调: 打印收到的上报 """
    print(f"Received message: {msg.payload.decode()} on topic {msg.topic}")


def create_raw_client():
    """ 创建原生 paho 客户端: 9002端口必须用 WebSocket + TLS """
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                         transport="websockets")
    client.ws_set_options(path=config.WS_PATH)
    client.tls_set()
    client.on_connect = on_connect
    client.on_message = on_message
    return client


def main():
    """ 连接平台并持续接收上报, Ctrl+C 退出 """
    client = create_raw_client()
    client.connect(config.BROKER, config.PORT_WSS, config.KEEPALIVE_SECS)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("程序退出, 关闭mqtt")
    finally:
        client.disconnect()


if __name__ == '__main__':
    main()
