"""
平台接入参数与设备指令常量

平台的两个端口指向同一个 broker(已实测消息互通):
    - 9002: MQTT over WebSocket + TLS, 即 wss://mqtt.yyzlab.com.cn:9002/mqtt
    - 1883: 明文 MQTT(TCP), 本地调试更方便
"""

from pathlib import Path

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

# ---------------- 数据集目录 ----------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = PROJECT_ROOT / "dataset"         # 数据集根目录(相对项目根, 与运行目录无关)
DATASET_RAW = DATASET_ROOT / "raw"              # 未成熟果实
DATASET_RIPE = DATASET_ROOT / "ripe"            # 成熟果实
DATASET_HALF_RIPE = DATASET_ROOT / "half-ripe"  # 半成熟果实

# ---------------- 数据集划分 ----------------
# 划分时按类别单独打乱, 每个类别取 prop_train 作为训练集, 剩余为验证集
DATASET_CATEGORIES = (DATASET_HALF_RIPE.name, DATASET_RAW.name, DATASET_RIPE.name)  # 参与划分的类别目录
DATASET_SPLIT_ROOT = PROJECT_ROOT / "dataset_split"        # 划分结果根目录
DATASET_SPLIT_TRAIN = DATASET_SPLIT_ROOT / "train"         # 训练集目录
DATASET_SPLIT_VALID = DATASET_SPLIT_ROOT / "valid"         # 验证集目录
PROP_TRAIN = 0.8                                           # 训练集占比, 验证集自动取剩余部分
SPLIT_SEED = 42                                            # 随机种子, 相同数据下结果可复现; None 表示每次随机

# ---------------- 图像报文 ----------------
KEY_IMAGE = "image"             # 图像报文的键, 值为 base64 编码的图片
IMAGE_SUFFIX = ".jpg"           # 图片保存后缀


def create_client(topic_sub=TOPIC_SUB, topic_pub=TOPIC_PUB,
                  use_websocket=True, use_tls=None, broker=None, port=None,
                  **client_kwargs):
    """
    按平台默认参数创建 Mqtt_Clt 客户端

    parameters:topic_sub:订阅主题(默认 lzm1, 接收设备上报)
            topic_pub:发布主题(默认 lzm0, 下发指令)
            use_websocket:True 走 9002(wss); False 走 1883(明文TCP)
            use_tls:是否启用TLS; 不传时跟随 use_websocket(9002开TLS, 1883不开)
            broker:broker地址, 不传用平台默认地址(如本地broker 127.0.0.1)
            port:broker端口, 不传时按传输方式取 PORT_WSS / PORT_TCP
            client_kwargs:透传给 Mqtt_Clt 的其它参数, 如 client_id
    """
    from conveyor.mqtt_client import Mqtt_Clt        # 延迟导入, 避免包内循环依赖

    if use_tls is None:
        use_tls = use_websocket
    broker = broker if broker is not None else BROKER
    if port is None:
        port = PORT_WSS if use_websocket else PORT_TCP
    return Mqtt_Clt(broker, port, topic_sub, topic_pub, KEEPALIVE_SECS,
                    use_websocket=use_websocket, ws_path=WS_PATH, use_tls=use_tls,
                    connect_timeout_secs=CONNECT_TIMEOUT_SECS, **client_kwargs)
