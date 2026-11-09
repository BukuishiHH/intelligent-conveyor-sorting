"""
MQTT 客户端封装

相比直接使用 paho-mqtt, 这里额外保证:
    1. 等待 broker 返回 CONNACK 才算连接成功, 避免"假连接";
    2. 在 on_connect 里订阅, 断线重连后会自动重新订阅;
    3. 发布后等待投递确认(wait_for_publish), 避免发完立即退出导致报文丢失;
    4. 支持 WebSocket + TLS(平台 9002 端口)。
"""

import json
import queue
import threading
import uuid

import paho.mqtt.client as mqtt


class Mqtt_Clt():
    """
    用于表征Mqtt客户端的类
    """

    def __init__(self, ip_broker, port_broker, topic_sub, topic_pub, time_out_secs,
                 use_websocket=False, ws_path="/mqtt", use_tls=False, client_id=None,
                 connect_timeout_secs=None):
        """
        parameters:ip_broker:broker的IP地址
                port_broker:连接服务的端口
                topic_sub:订阅话题（收消息）
                topic_pub:发布话题（发指令）
                time_out_secs:MQTT心跳间隔(秒)
                use_websocket:是否使用WebSocket传输(平台9002端口需要为True)
                ws_path:WebSocket路径, 平台为"/mqtt"
                use_tls:是否使用TLS加密(平台9002端口需要为True)
                client_id:客户端ID, 默认按UUID自动生成, 避免多客户端互相顶号
                connect_timeout_secs:等待CONNACK的超时(秒), 默认与心跳间隔相同
        """
        self.ip_broker = ip_broker
        self.port_broker = port_broker
        self.topic_sub = topic_sub                                      # 订阅主题, 用来接收设备上报数据
        self.topic_pub = topic_pub                                      # 发布主题, 用来下发控制指令给设备
        self.time_out_secs = time_out_secs
        self.connect_timeout_secs = (connect_timeout_secs
                                     if connect_timeout_secs is not None else time_out_secs)
        self.mqtt_queue = queue.Queue(5)                                # 创建容量为5的线程安全队列, 缓存收到的消息
        self.connected = False
        self._connect_event = threading.Event()                         # 用于等待CONNACK, 避免"假连接"

        self.mqtt_clt = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,       # 构造Mqtt客户端
            client_id=client_id or f"hq007_{uuid.uuid4().hex[:12]}",     # 唯一客户端ID, 防止空ID互相顶号
            transport="websockets" if use_websocket else "tcp",
        )
        self.mqtt_clt.on_connect = self.on_connect
        self.mqtt_clt.on_disconnect = self.on_disconnect
        self.mqtt_clt.on_message = self.on_message                      # 设置消息回调函数
        if use_websocket:
            self.mqtt_clt.ws_set_options(path=ws_path)                  # 9002端口: wss://ip:9002/mqtt
        if use_tls:
            self.mqtt_clt.tls_set()                                     # 使用系统CA校验证书(平台证书由Let's Encrypt签发)

        self.mqtt_clt.connect(ip_broker, port_broker, time_out_secs)    # 连接MQTT代理broker(TCP/TLS握手, 阻塞)
        self.mqtt_clt.loop_start()                                      # 开启后台网络循环, 非阻塞

        # 等待broker返回CONNACK, 否则程序可能在"未真正连上"的情况下直接发消息然后退出
        if not self._connect_event.wait(self.connect_timeout_secs):
            self.close()
            raise TimeoutError(f"等待MQTT连接确认超时({self.connect_timeout_secs}s): "
                               f"{ip_broker}:{port_broker}")
        if not self.connected:
            self.close()
            raise ConnectionError(f"MQTT连接被拒绝: {ip_broker}:{port_broker}")

    # MQTT连接回调
    def on_connect(self, client, userdata, connect_flags, reason_code, properties):
        code = getattr(reason_code, "value", reason_code)
        if code == 0:
            self.connected = True
            # 在连接成功回调里订阅, 断线重连后会自动重新订阅(放在__init__里只会订阅一次)
            self.mqtt_clt.subscribe(self.topic_sub, qos=1)              # QoS1: 至少收到一次
            print(f"MQTT连接成功, 已订阅主题 {self.topic_sub}")
        else:
            self.connected = False
            print(f"MQTT连接失败, reason_code={code}")
        self._connect_event.set()

    # MQTT断开回调
    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        code = getattr(reason_code, "value", reason_code)
        self.connected = False
        if code != 0:                                                   # 0 表示主动断开, 非0为异常断开
            print(f"MQTT连接异常断开, reason_code={code}, 等待自动重连...")

    # MQTT消息回调
    def on_message(self, client, userdata, message):
        try:
            data = json.loads(message.payload.decode("utf-8"))
            self.mqtt_queue.put_nowait(data)
        except queue.Full:
            print("消息队列满, 丢弃报文")
        except Exception as e:
            print("报文解析错误: ", e)

    # 发送JSON消息, 返回MQTTMessageInfo, 可用来确认broker是否收到
    def send_json_msg(self, msg_dict: dict, qos: int = 1, retain: bool = False,
                      wait: bool = True, timeout: float = 5.0):
        payload = json.dumps(msg_dict, ensure_ascii=False)
        info = self.mqtt_clt.publish(self.topic_pub, payload=payload, qos=qos, retain=retain)
        if wait:
            # 等待报文真正投递(QoS0: 已写入socket; QoS1: 已收到broker的PUBACK)
            # publish后立即退出时, 网络线程可能还没把报文发出去, 这是"控制台结束但没收到"的隐患之一
            info.wait_for_publish(timeout=timeout)
        return info

    # 控制设备, 快捷封装
    def control_device(self, str_key, str_value, wait: bool = True, timeout: float = 5.0):
        print(f"下发指令: {str_key}={str_value} -> 主题 {self.topic_pub}")
        return self.send_json_msg({str_key: str_value}, wait=wait, timeout=timeout)

    # 关闭MQTT连接
    def close(self):
        self.mqtt_clt.disconnect()          # 先发DISCONNECT, 让broker正常清理会话
        self.mqtt_clt.loop_stop()           # 再停止网络线程
        self.connected = False
