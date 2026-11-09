# 智能流水线分拣 · MQTT 控制

基于 **paho-mqtt 2.x** 的流水线设备控制示例：通过 MQTT 向传送带 / 推杆下发指令，并接收设备上报。

项目使用实验平台的真实接入参数（`mqtt.yyzlab.com.cn`），核心价值在于把 MQTT 使用中最容易踩的三个坑处理干净：

1. **等 CONNACK 才算连上** —— 避免 `connect()` 返回就以为成功（"假连接"）；
2. **在 `on_connect` 里订阅** —— 断线重连后自动重新订阅，不会静默失聪；
3. **发布后等投递确认** —— QoS1 + `wait_for_publish()`，避免 `publish()` 之后立即退出导致报文从未发出。

---

## 1. 目录结构

```text
intelligent-conveyor-sorting/
├── conveyor/                    # 核心库（可复用）
│   ├── __init__.py              # 导出 Mqtt_Clt 与 config
│   ├── config.py                # 平台接入参数 + 指令常量 + create_client()
│   └── mqtt_client.py           # Mqtt_Clt：连接/订阅/发布/收报的封装
├── scripts/                     # 可执行入口
│   ├── control_conveyor.py      # 传送带停止（最简示例）
│   ├── control_rod_control.py   # 传送带运行 + 推杆往复循环
│   ├── recv_msg.py              # 收设备上报 + 下发一串动作
│   ├── pub_mqtt.py              # 原生 paho 发布示例
│   └── sub_mqtt.py              # 原生 paho 订阅示例
├── tests/                       # pytest 单元测试（全部离线，不需要 broker）
│   ├── conftest.py              # FakePahoClient 与公共 fixture
│   ├── test_config.py
│   ├── test_mqtt_client.py
│   ├── test_control_conveyor.py
│   ├── test_control_rod_control.py
│   ├── test_recv_msg.py
│   ├── test_pub_mqtt.py
│   └── test_sub_mqtt.py
├── pytest.ini                   # pytest 配置（testpaths / pythonpath）
├── requirements.txt
├── .gitignore
└── README.md
```

分层约定：

| 层 | 目录 | 职责 |
| --- | --- | --- |
| 核心库 | `conveyor/` | 只做 MQTT 通信与参数定义，不写业务循环 |
| 入口脚本 | `scripts/` | 组装业务动作，包含 `main()` 与 `if __name__ == '__main__'` |
| 测试 | `tests/` | 每个模块一个测试文件，用替身替代真实网络 |

---

## 2. 环境准备

```powershell
# 建议使用虚拟环境；本项目在 Python 3.11 + paho-mqtt 2.2.0 下验证
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

依赖仅两项：

- `paho-mqtt >= 2.0`：必须 2.x，代码使用了 `CallbackAPIVersion.VERSION2` 回调签名；
- `pytest >= 7.0`：仅测试需要（`pytest.ini` 用到 `pythonpath` 配置项）。

> 说明：`conveyor/` 与 `scripts/` 均在仓库根目录，**无需 `pip install` 本项目**，在仓库根目录运行即可。

---

## 3. 快速开始

所有命令都在**仓库根目录**执行：

```powershell
# 1) 传送带停止（最安全的连通性验证：执行后打印"结束"即表示已连上 broker）
python .\scripts\control_conveyor.py

# 2) 传送带运行 + 推杆往复（Ctrl+C 退出）
python .\scripts\control_rod_control.py

# 3) 一边收设备上报，一边下发一串动作（Ctrl+C 退出）
python .\scripts\recv_msg.py

# 4) 原生 paho 示例：发布一条文本消息 / 订阅设备上报
python .\scripts\pub_mqtt.py
python .\scripts\sub_mqtt.py
```

也可以按模块方式运行（等价）：

```powershell
python -m scripts.control_conveyor
```

### 典型输出

```text
MQTT连接成功, 已订阅主题 lzm1
下发指令: conveyor=stop -> 主题 lzm0
指令已确认送达broker
结束
```

`recv_msg.py` 收到设备上报时：

```text
收到上报:  {'conveyor': 'run'}
```

---

## 4. 接入参数与通信协议

### 4.1 连接参数

| 参数 | 值 | 说明 |
| --- | --- | --- |
| broker | `mqtt.yyzlab.com.cn` | 平台地址（证书由 Let's Encrypt 签发，系统 CA 可直接校验） |
| 端口 | `9002` | **MQTT over WebSocket + TLS**，完整地址 `wss://mqtt.yyzlab.com.cn:9002/mqtt` |
| 端口 | `1883` | 明文 MQTT（TCP）。与 9002 是**同一个 broker**，消息互通 |
| WebSocket 路径 | `/mqtt` | 9002 端口专有 |
| 心跳 | 60 s | `connect(..., keepalive=60)` |
| 连接确认超时 | 10 s | 等待 CONNACK，超时抛 `TimeoutError` |
| 发布确认超时 | 5 s | `wait_for_publish(timeout=5)` |

> ⚠️ 9002 **不是裸 MQTT TCP 端口**：直接以 TCP 连接会收到 TLS alert，必须走 `wss` 且路径为 `/mqtt`。

### 4.2 主题（注意方向）

设备端给出的参数是 `subtopic=lzm0`、`pubtopic=lzm1`，针对的是**设备自己**：

| 主题 | 设备侧行为 | 程序侧行为 | 用途 |
| --- | --- | --- | --- |
| `lzm0` | 订阅 | **发布** | 下发控制指令给设备 |
| `lzm1` | 发布 | **订阅** | 接收设备上报 |

因此代码中固定为：`TOPIC_PUB = "lzm0"`、`TOPIC_SUB = "lzm1"`。

> `Mqtt_Clt(ip, port, topic_sub, topic_pub, ...)` 的参数顺序是**先订阅、后发布**，
> 调用时不要把两个主题写反，否则会变成"自己发、自己收"，设备毫无反应。

### 4.3 消息格式

指令为单键 JSON 对象（UTF-8，`ensure_ascii=False`）：

| 指令 | payload |
| --- | --- |
| 传送带运行 | `{"conveyor": "run"}` |
| 传送带停止 | `{"conveyor": "stop"}` |
| 推杆推出 | `{"rod_control": "first_push"}` |
| 推杆拉回 | `{"rod_control": "first_pull"}` |

对应的常量都在 `conveyor/config.py`：

```python
KEY_CONVEYOR, KEY_ROD_CONTROL = "conveyor", "rod_control"
CONVEYOR_RUN, CONVEYOR_STOP = "run", "stop"
ROD_FIRST_PUSH, ROD_FIRST_PULL = "first_push", "first_pull"
```

---

## 5. 核心 API

### 5.1 `conveyor.config`

| 名称 | 说明 |
| --- | --- |
| `BROKER` / `PORT_WSS` / `PORT_TCP` / `WS_PATH` | 平台地址与端口、WebSocket 路径 |
| `KEEPALIVE_SECS` / `CONNECT_TIMEOUT_SECS` / `PUBLISH_TIMEOUT_SECS` | 心跳、连接确认、发布确认超时 |
| `TOPIC_SUB` / `TOPIC_PUB` | `lzm1` / `lzm0` |
| `create_client(...)` | 按平台默认参数创建 `Mqtt_Clt`；`use_websocket=False` 时自动走 1883 明文并关闭 TLS |

```python
from conveyor import config

client = config.create_client()                       # 默认 wss 9002
client = config.create_client(use_websocket=False)    # 调试用 1883 明文
client = config.create_client(topic_sub="lzm1", topic_pub="lzm0", client_id="my-id")
```

### 5.2 `conveyor.mqtt_client.Mqtt_Clt`

构造参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `ip_broker` / `port_broker` | 必填 | broker 地址与端口 |
| `topic_sub` / `topic_pub` | 必填 | 订阅主题、发布主题 |
| `time_out_secs` | 必填 | MQTT 心跳间隔（秒） |
| `use_websocket` | `False` | 是否 WebSocket 传输（9002 需 `True`） |
| `ws_path` | `"/mqtt"` | WebSocket 路径 |
| `use_tls` | `False` | 是否 TLS（9002 需 `True`） |
| `client_id` | 自动生成 | 默认 `hq007_<uuid12>`，避免多客户端顶号 |
| `connect_timeout_secs` | 同心跳 | 等待 CONNACK 的超时，超时抛 `TimeoutError` |

实例方法：

| 方法 | 说明 |
| --- | --- |
| `send_json_msg(msg_dict, qos=1, retain=False, wait=True, timeout=5.0)` | 发布 JSON，默认等待投递确认，返回 `MQTTMessageInfo` |
| `control_device(key, value, wait=True, timeout=5.0)` | 下发单键指令的特快捷封装，返回 `MQTTMessageInfo` |
| `close()` | 先 `disconnect()` 再 `loop_stop()`，顺序不可颠倒 |
| `mqtt_queue` | `queue.Queue(5)`，`on_message` 解析后的消息进入这里，队列满则丢弃并提示 |
| `connected` | 当前连接状态（由 `on_connect` / `on_disconnect` 维护） |

使用示例：

```python
from conveyor import config

mqtt_client = config.create_client()
try:
    info = mqtt_client.control_device(config.KEY_CONVEYOR, config.CONVEYOR_STOP)
    print("已送达" if info.is_published() else "未确认")
finally:
    mqtt_client.close()
```

异常语义：

- `TimeoutError`：`connect()` 完成但 10 s 内没有 CONNACK（端口/协议不匹配、网络被拦）；
- `ConnectionError`：broker 明确返回非 0 的 CONNACK（如 5 = Not authorized）；
- `RuntimeError`（来自 paho）：`wait_for_publish` 超时，说明 broker 未在 5 s 内确认。

---

## 6. 测试

测试只依赖 `pytest`，**全部离线运行**：`tests/conftest.py` 里的 `FakePahoClient` 替换了 `paho.mqtt.client.Client`，
并让 `loop_start()` 立即回调 `on_connect`（模拟 broker 返回 CONNACK），因此不需要网络、不会向设备发指令。

```powershell
# 全部测试（在仓库根目录）
python -m pytest

# 只看某个模块 / 某个用例
python -m pytest tests\test_mqtt_client.py
python -m pytest tests\test_mqtt_client.py -k "timeout"

# 显示每个用例名
python -m pytest -v
```

| 测试文件 | 覆盖内容 |
| --- | --- |
| `test_config.py` | 常量取值正确；`create_client` 的参数映射（wss/明文、TLS 跟随、主题与 client_id 透传） |
| `test_mqtt_client.py` | 传输与 TLS 选项、CONNACK 等待、超时/拒绝异常、on_connect 订阅、client_id 唯一性、JSON 发布参数与确认、消息解析/队列满/解析失败、断线与关闭顺序 |
| `test_control_conveyor.py` | 下发 `conveyor=stop`、送达/未送达提示、异常时仍关闭连接、"结束"输出 |
| `test_control_rod_control.py` | 先 `conveyor=run` 再 `rod_control=first_push`、Ctrl+C 退出与关闭 |
| `test_recv_msg.py` | 收报打印与线程退出、动作下发顺序、Ctrl+C 清理 |
| `test_pub_mqtt.py` | 原生客户端 wss 配置、连接回调输出、发布参数与等待确认、断开顺序 |
| `test_sub_mqtt.py` | 订阅 `lzm1`、连接失败不订阅、消息打印、`loop_forever` 中断后断开 |

当前结果：**39 passed**。

> 测试替身只模拟行为、不校验真实 broker 语义；真实链路仍需用 `control_conveyor.py` + MQTTX 联合验证。

---

## 7. MQTTX 客户端配置

想用图形客户端观察报文，必须配对协议，否则连不上 9002：

| 配置项 | 值 |
| --- | --- |
| Host | `mqtt.yyzlab.com.cn` |
| Port | `9002` |
| Protocol | `ws` |
| SSL/TLS | **开启**（即 `wss`） |
| Path | `/mqtt` |

订阅建议：

- 订阅 `lzm0` → 看到本程序下发的控制指令；
- 订阅 `lzm1` → 看到设备上报（同时也是判断设备在线的唯一依据）。

若 MQTTX 版本不支持 `ws + TLS` 组合，直接改连 `1883`（明文 mqtt），收发的消息完全一样。

---

## 8. 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 打印"结束"但没人收到消息 | 旧实现 `publish()` 后立即退出，QoS0 报文可能没发出去 | 已改为 QoS1 + `wait_for_publish()`；若仍失败会打印"指令未被broker确认" |
| 连接直接抛 `TimeoutError` | 9002 被当成裸 MQTT TCP，或路径不是 `/mqtt` | 必须 `transport="websockets"` + `tls_set()` + `ws_set_options(path="/mqtt")` |
| 抛 `ConnectionError`，日志 `reason_code=5` | 账号/ACL 不允许该 client 或主题 | 检查平台侧设备与主题权限 |
| MQTTX 连不上 9002 | 用了 `mqtt://` 或未开 TLS | 改 `ws` + SSL，路径 `/mqtt`；或临时改连 1883 |
| 指令已送达 `lzm0` 但设备不动 | 设备离线 / 未连到同一 broker / payload 字段不符 | 先用 `python .\scripts\sub_mqtt.py` 看 `lzm1` 有没有上报；核对 JSON 键名 |
| 订阅 `lzm1` 完全没有报文 | 设备端可能把 9002 当成明文 TCP 端口在连 | 让设备改用 1883，或改用 `wss` + `/mqtt` |
| 两个程序互相顶号掉线 | 早期版本 client_id 为空或重复 | 现在默认 `hq007_<uuid12>`，也可显式传 `client_id` |
| 收报队列满，提示"消息队列满, 丢弃报文" | `queue.Queue(5)` 已满，消费线程太慢 | 在 `recv_msg.get_message()` 中加快消费，或调大队列容量 |

自检顺序（推荐）：

1. `python .\scripts\control_conveyor.py` —— 能打印"MQTT连接成功"和"结束"，说明链路与 TLS 正常；
2. MQTTX 订阅 `lzm0`，再跑一次 —— 应看到 `{"conveyor": "stop"}`（注意可能有一条旧的重试报文）；
3. `python .\scripts\sub_mqtt.py` 观察 `lzm1` —— 有上报说明设备在线，可继续测试 `run` / `first_push`；
4. 设备无任何上报时，问题在设备侧（在线状态、broker 地址、端口协议），与上位机脚本无关。

---

## 9. 从旧版本迁移

早期版本是根目录平铺的脚本，重构后对应关系如下：

| 旧路径 | 新路径 |
| --- | --- |
| `MQTT_Clt.py` | `conveyor/mqtt_client.py`（类名仍为 `Mqtt_Clt`） |
| `control_conveyor.py` | `scripts/control_conveyor.py` |
| `control_rod_control.py` | `scripts/control_rod_control.py` |
| `recv_msg.py` | `scripts/recv_msg.py` |
| `pub_mqtt.py` | `scripts/pub_mqtt.py` |
| `sub_mqtt.py` | `scripts/sub_mqtt.py` |

导入方式变化：

```python
# 旧
from MQTT_Clt import Mqtt_Clt

# 新
from conveyor.mqtt_client import Mqtt_Clt
from conveyor import config
```

平台参数不再散落在各脚本里，统一在 `conveyor/config.py` 维护。

---

## 10. 设计要点与已知限制

设计要点：

- **订阅位置**：`subscribe()` 写在 `on_connect` 回调内，重连后自动恢复；写在 `__init__` 里只在首次生效。
- **发布确认**：`wait_for_publish()` 只是确认"broker 收到"，不代表"设备执行"；设备执行结果必须看 `lzm1` 上报。
- **关闭顺序**：`disconnect()` → `loop_stop()`，先发 DISCONNECT 让 broker 正常清理会话，再停网络线程。
- **队列解耦**：`on_message` 只做解析入队，业务线程通过 `mqtt_queue` 消费，避免阻塞 paho 网络线程。
- **唯一 client_id**：避免同 ID 客户端互踢，导致"时而收得到、时而收不到"。

已知限制：

- 未实现持久会话（`clean_session=False` / `session_expiry`），断线期间下发的 QoS1 报文不会补发；
- `retain` 默认关闭，指令不会被 broker 保留给后上线的设备（旧用例中 `lzm0` 存在一条历史 retained 报文，测试时可能先收到它）；
- 未做 TLS 证书固定（pinning）与双向认证，仅依赖系统 CA 校验服务端证书；
- 设备侧行为（是否执行、执行结果）不在本仓库范围内，需结合设备固件与平台日志排查。

---

## 11. 参考

- paho-mqtt 官方文档：<https://eclipse.dev/paho/files/paho.mqtt.python/html/index.html>
- MQTT 5.0 规范：<https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html>
- WebSocket（RFC 6455）：<https://datatracker.ietf.org/doc/html/rfc6455>


