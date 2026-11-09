""" MQTT 发布示例: 直接用 paho 向平台发布一条文本消息 """

import sys
from pathlib import Path

# 支持 `python scripts/pub_mqtt.py` 直接运行
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import paho.mqtt.client as mqtt

from conveyor import config

topic = config.TOPIC_PUB
message = 'Hello, MQTT!'


def on_connect(client, userdata, connect_flags, reason_code, properties):
    """ 连接回调: 打印连接结果 """
    if getattr(reason_code, "value", reason_code) == 0:
        print("Connected successfully.")
    else:
        print(f"Connection failed, reason_code={reason_code}")


def create_raw_client():
    """ 创建原生 paho 客户端: 9002端口必须用 WebSocket + TLS """
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                         transport="websockets")
    client.ws_set_options(path=config.WS_PATH)
    client.tls_set()
    client.on_connect = on_connect
    return client


def main():
    """ 连接平台, 发布一条示例消息并等待投递确认 """
    client = create_raw_client()
    client.connect(config.BROKER, config.PORT_WSS, config.KEEPALIVE_SECS)
    client.loop_start()
    try:
        info = client.publish(topic, message, qos=1)
        info.wait_for_publish(timeout=config.PUBLISH_TIMEOUT_SECS)
        print(f"已发布到 {topic}: {message}")
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == '__main__':
    main()
