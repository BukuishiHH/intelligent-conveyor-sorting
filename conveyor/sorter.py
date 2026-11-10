"""
自动分拣: 图像识别结果 + 光电对管上报 -> 推杆动作

控制逻辑与原始示例一致:
    1. 启动: 传送带运行, 所有推杆拉回, 延时推出上料推杆;
    2. 收到图像报文: 解码 base64 并识别, 记录当前类别(同一时间只跟踪一个果实);
    3. 收到对管报文: 当前类别与对管对应时, 立即推出分拣推杆, 并延时补料;
       每个推杆推出后保持 push_secs 再自动拉回。

报文格式(JSON):
    {"image": "<base64编码的图片>"}     # 图像上报
    {"first_switch": false}             # 光电对管上报(示例设备低电平有效)
"""

import queue
import threading
import time

from conveyor import config
from conveyor.predictor import ResNetPredictor


class ConveyorSorter():
    """ 用识别结果和光电对管上报控制推杆, 完成自动分拣的类 """

    def __init__(self, mqtt_client, predictor=None,
                 load_rod=config.ROD_LOAD,
                 class_rods=None, switch_classes=None,
                 push_secs=config.ROD_PUSH_SECS,
                 reload_delay=config.ROD_RELOAD_DELAY_SECS,
                 start_delay=config.ROD_START_DELAY_SECS,
                 switch_active_value=config.SWITCH_ACTIVE_VALUE,
                 verbose=True):
        """
        parameters:mqtt_client:Mqtt_Clt实例(需已连接并订阅设备上报主题)
                predictor:ResNetPredictor实例, 为None时自动创建(首次识别才加载权重)
                load_rod:上料推杆序号, 默认"first"
                class_rods:类别 -> 分拣推杆序号, 默认 ripe/half-ripe/raw 对应 second/third/fourth
                switch_classes:对管键名 -> 类别, 默认 first_switch/second_switch/third_switch
                push_secs:推杆推出后保持时间(秒)
                reload_delay:分拣推杆动作后补料推杆的延时(秒)
                start_delay:启动后首次推出上料推杆的延时(秒)
                switch_active_value:对管触发时的上报值, 示例设备为False(低电平有效)
                verbose:是否打印识别与推杆信息
        """
        self.mqtt_client = mqtt_client
        self.load_rod = load_rod
        self.class_rods = dict(class_rods) if class_rods is not None else {
            "ripe": config.ROD_RIPE,
            "half-ripe": config.ROD_HALF_RIPE,
            "raw": config.ROD_RAW,
        }
        self.switch_classes = dict(switch_classes) if switch_classes is not None else {
            config.SWITCH_RIPE: "ripe",
            config.SWITCH_HALF_RIPE: "half-ripe",
            config.SWITCH_RAW: "raw",
        }
        missing = set(self.switch_classes.values()) - set(self.class_rods)
        if missing:
            raise ValueError(f"对管对应的类别缺少推杆映射: {sorted(missing)}")
        self.predictor = predictor if predictor is not None else ResNetPredictor(verbose=verbose)
        self.push_secs = push_secs
        self.reload_delay = reload_delay
        self.start_delay = start_delay
        self.switch_active_value = switch_active_value
        self.verbose = verbose

        self.current_class = None               # 最近一次识别出的类别
        self._timers = set()                    # 未执行完的推杆定时器, 退出时统一取消
        self._timers_lock = threading.Lock()
        self._stop_event = threading.Event()

    def start(self):
        """ 启动传送带、拉回所有推杆, 并延时推出上料推杆 """
        self.mqtt_client.control_device(config.KEY_CONVEYOR, config.CONVEYOR_RUN)
        self.mqtt_client.control_device(config.KEY_ROD_CONTROL, config.ROD_ALL_PULL)
        self.schedule(self.start_delay, self.load_rod)

    def run(self, poll_secs=0.5):
        """
        启动设备并循环处理 MQTT 报文, 直到 close() 或 Ctrl+C

        parameters:poll_secs:队列取报文超时(秒), 用于及时响应停止事件
        """
        self.start()
        while not self._stop_event.is_set():
            try:
                msg = self.mqtt_client.mqtt_queue.get(timeout=poll_secs)
            except queue.Empty:
                continue                        # 队列暂无数据, 继续等待
            self.handle_message(msg)

    def handle_message(self, msg):
        """
        处理一条设备上报: 图像报文做识别, 其他报文按对管触发处理

        parameters:msg:已解析的JSON报文(通常为dict)

        returns:图像报文返回识别结果字典, 其他报文返回None
        """
        if not isinstance(msg, dict):
            return None
        if config.KEY_IMAGE in msg:
            return self.identify(msg[config.KEY_IMAGE])
        self.handle_switch(msg)
        return None

    def identify(self, image_base64):
        """
        识别一帧base64图片并记录当前类别

        parameters:image_base64:base64编码的图片字符串

        returns:识别结果字典, 解码或推理失败返回None(不中断分拣循环)
        """
        try:
            result = self.predictor.predict_base64(image_base64)
        except Exception as e:
            self.log(f"图像识别失败, 已跳过该报文: {e}")
            return None
        self.current_class = result["class_name"]
        self.log(f"识别结果: {self.current_class}, 概率: {result['probability']:.4f}, "
                 f"推理耗时: {result['timings']['inference']:.1f}ms")
        return result

    def handle_switch(self, msg):
        """
        对管触发时, 按当前识别类别推出对应分拣推杆, 并延时补料

        parameters:msg:对管报文, 如 {"first_switch": False}
        """
        for switch_key, class_name in self.switch_classes.items():
            if switch_key not in msg or msg[switch_key] != self.switch_active_value:
                continue                        # 不是该对管的触发报文
            if self.current_class != class_name:
                continue                        # 当前果实不属于该对管对应的类别
            rod = self.class_rods[class_name]
            self.log(f"对管 {switch_key} 触发, 类别 {class_name} -> 推杆 {rod}")
            self.schedule(0.0, rod)                              # 立即推出分拣推杆
            self.schedule(self.reload_delay, self.load_rod)      # 延时补料

    def push_pull(self, rod):
        """
        推出指定推杆, 保持 push_secs 后拉回

        parameters:rod:推杆序号, 如 second
        """
        self.mqtt_client.control_device(config.KEY_ROD_CONTROL, f"{rod}_push")
        time.sleep(self.push_secs)
        self.mqtt_client.control_device(config.KEY_ROD_CONTROL, f"{rod}_pull")

    def schedule(self, delay, rod):
        """
        延时执行推杆动作, 返回Timer; 定时器设为daemon, 退出时统一取消

        parameters:delay:延时(秒), 0表示立即在新线程中执行
                rod:推杆序号
        """
        timer = threading.Timer(delay, self._run_rod, args=(rod,))
        timer.daemon = True
        with self._timers_lock:
            self._timers.add(timer)
        timer.start()
        return timer

    def _run_rod(self, rod):
        """ 定时器回调: 执行推杆动作, 无论成败都从待执行集合中移除自己 """
        try:
            self.push_pull(rod)
        except Exception as e:
            self.log(f"推杆动作失败({rod}): {e}")
        finally:
            with self._timers_lock:
                self._timers.discard(threading.current_thread())

    def close(self):
        """ 取消未执行的推杆动作, 等待正在执行的推杆复位, 停止传送带并关闭MQTT """
        self._stop_event.set()
        with self._timers_lock:
            timers, self._timers = list(self._timers), set()
        for timer in timers:
            timer.cancel()
        for timer in timers:
            if timer.is_alive():
                timer.join(timeout=self.push_secs + 1)   # 等推出中的推杆拉回, 避免停在推出状态
        try:
            self.mqtt_client.control_device(config.KEY_CONVEYOR, config.CONVEYOR_STOP)
        except Exception as e:
            self.log(f"停止传送带失败, 请手动确认设备状态: {e}")
        self.mqtt_client.close()

    def log(self, message):
        """ verbose 为 True 时打印 """
        if self.verbose:
            print(message)
