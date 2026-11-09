"""
平台接入参数与设备指令常量

平台的两个端口指向同一个 broker(已实测消息互通):
    - 9002: MQTT over WebSocket + TLS, 即 wss://mqtt.yyzlab.com.cn:9002/mqtt
    - 1883: 明文 MQTT(TCP), 本地调试更方便
"""

# ---------------- 连接参数 ----------------
BROKER = "mqtt.yyzlab.com.cn"
PORT_WSS = 9002                 # MQTT over WebSocket + TLS
PORT_TCP = 1883                 # 明文 MQTT(TCP)
WS_PATH = "/mqtt"               # 9002端口的 WebSocket 路径
KEEPALIVE_SECS = 60             # MQTT 心跳间隔(秒)
CONNECT_TIMEOUT_SECS = 10.0     # 等待 broker 返回 CONNACK 的超时(秒)
PUBLISH_TIMEOUT_SECS = 5.0      # 等待报文投递确认的超时(秒)

# ---------------- 主题 ----------------
# 设备端给出的参数: subtopic=lzm0(设备收指令), pubtopic=lzm1(设备发上报)
TOPIC_SUB = "lzm1"              # 程序订阅: 接收设备上报数据
TOPIC_PUB = "lzm0"              # 程序发布: 下发控制指令给设备

# ---------------- 指令常量 ----------------
KEY_CONVEYOR = "conveyor"       # 传送带指令键
KEY_ROD_CONTROL = "rod_control"  # 推杆指令键
CONVEYOR_RUN = "run"            # 传送带运行
CONVEYOR_STOP = "stop"          # 传送带停止
ROD_FIRST_PUSH = "first_push"   # 推杆推出
ROD_FIRST_PULL = "first_pull"   # 推杆拉回


def create_client(topic_sub=TOPIC_SUB, topic_pub=TOPIC_PUB,
                  use_websocket=True, use_tls=None, **client_kwargs):
    """
    按平台默认参数创建 Mqtt_Clt 客户端

    parameters:topic_sub:订阅主题(默认 lzm1, 接收设备上报)
            topic_pub:发布主题(默认 lzm0, 下发指令)
            use_websocket:True 走 9002(wss); False 走 1883(明文TCP)
            use_tls:是否启用TLS; 不传时跟随 use_websocket(9002开TLS, 1883不开)
            client_kwargs:透传给 Mqtt_Clt 的其它参数, 如 client_id
    """
    from conveyor.mqtt_client import Mqtt_Clt        # 延迟导入, 避免包内循环依赖

    if use_tls is None:
        use_tls = use_websocket
    port = PORT_WSS if use_websocket else PORT_TCP
    return Mqtt_Clt(BROKER, port, topic_sub, topic_pub, KEEPALIVE_SECS,
                    use_websocket=use_websocket, ws_path=WS_PATH, use_tls=use_tls,
                    connect_timeout_secs=CONNECT_TIMEOUT_SECS, **client_kwargs)
