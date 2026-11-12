# 智能流水线分拣 · MQTT 控制

基于 **paho-mqtt 2.x** 的流水线设备控制示例：通过 MQTT 向传送带 / 推杆下发指令，并接收设备上报。

项目使用实验平台的真实接入参数（`mqtt.yyzlab.com.cn`），核心价值在于把 MQTT 使用中最容易踩的三个坑处理干净：

1. **等 CONNACK 才算连上** —— 避免 `connect()` 返回就以为成功（"假连接"）；
2. **在 `on_connect` 里订阅** —— 断线重连后自动重新订阅，不会静默失聪；
3. **发布后等投递确认** —— QoS1 + `wait_for_publish()`，避免 `publish()` 之后立即退出导致报文从未发出。

在此之上还提供**数据集采集**：订阅设备上报的 base64 图片报文，落盘为 `dataset/<成熟度>/imgN.jpg`；**数据集划分**：按类别随机打乱后复制为 `dataset_split/train` 与 `dataset_split/valid`；**模型训练**：用 ResNet-18/34/50 完成训练、验证与保存；**单图推理**：加载训练好的权重，输出成熟度类别、概率与各阶段耗时；**自动分拣**：把 MQTT 图像报文、ResNet 推理与光电对管 / 推杆控制串成闭环（见第 6、7、8、9 节）。


---

## 1. 目录结构

```text
intelligent-conveyor-sorting/
├── conveyor/                    # 核心库（可复用）
│   ├── __init__.py              # 导出 Mqtt_Clt 与 config
│   ├── config.py                # 平台接入参数 + 指令常量 + 数据集/划分/训练/推理配置 + create_client()
│   ├── dataset.py               # GetData：收 base64 图片并落盘为数据集
│   ├── dataset_split.py         # SplitDataset：按类别随机划分 train / valid
│   ├── resnet.py                # ResNet-18/34/50 网络定义与预训练权重加载
│   ├── trainer.py               # ResNetTrainer：训练 / 验证 / 保存 / 混淆矩阵
│   ├── predictor.py             # ResNetPredictor：单图/内存/base64 推理、预处理、预热、可视化
│   ├── sorter.py                # ConveyorSorter：识别结果 + 光电对管 -> 推杆分拣
│   ├── profile.py               # Profile：代码段耗时测量（CUDA 计时前同步）
│   └── mqtt_client.py           # Mqtt_Clt：连接/订阅/发布/收报的封装
├── scripts/                     # 可执行入口
│   ├── control_conveyor.py      # 传送带停止（最简示例）
│   ├── control_rod_control.py   # 传送带运行 + 推杆往复循环
│   ├── get_dataset.py           # 数据集采集（Ctrl+C 退出）
│   ├── split_dataset.py         # 数据集划分（只复制不移动）
│   ├── train_resnet.py          # ResNet 训练 / 验证 / 保存模型
│   ├── predict_resnet.py        # 单图推理（类别 / 概率 / 各阶段耗时）
│   ├── sort_conveyor.py         # 自动分拣主程序（识别 + 对管 + 推杆）
│   ├── recv_msg.py              # 收设备上报 + 下发一串动作
│   ├── pub_mqtt.py              # 原生 paho 发布示例
│   └── sub_mqtt.py              # 原生 paho 订阅示例
├── dataset/                     # 采集输出（运行时生成，已被 .gitignore 忽略）
│   ├── raw/                     # 未成熟
│   ├── ripe/                    # 成熟
│   └── half-ripe/               # 半成熟
├── dataset_split/               # 划分输出（运行时生成，已被 .gitignore 忽略）
│   ├── train/                   # 训练集（80%）
│   │   ├── raw/
│   │   ├── ripe/
│   │   └── half-ripe/
│   └── valid/                   # 验证集（剩余 20%）
│       ├── raw/
│       ├── ripe/
│       └── half-ripe/
├── pre_model/                   # ImageNet 预训练权重（运行时放置，已被 .gitignore 忽略）
│   └── resnet18-f37072fd.pth
├── model/                       # 训练 / 推理输出（运行时生成，已被 .gitignore 忽略）
│   ├── best.pth                 # 验证准确率最高的模型
│   ├── last.pth                 # 最后一轮模型
│   ├── confusion_matrix.png     # 验证集混淆矩阵
│   └── predict_result.png       # 单图推理的可视化结果
├── tests/                       # pytest 单元测试（全部离线，不需要 broker）
│   ├── conftest.py              # FakePahoClient 与公共 fixture
│   ├── test_config.py
│   ├── test_mqtt_client.py
│   ├── test_control_conveyor.py
│   ├── test_control_rod_control.py
│   ├── test_dataset.py
│   ├── test_dataset_split.py
│   ├── test_resnet.py
│   ├── test_trainer.py
│   ├── test_profile.py
│   ├── test_predictor.py
│   ├── test_get_dataset.py
│   ├── test_split_dataset.py
│   ├── test_train_resnet.py
│   ├── test_predict_resnet.py
│   ├── test_sorter.py
│   ├── test_sort_main.py
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
| 核心库 | `conveyor/` | MQTT 通信、参数定义、数据集处理、ResNet 训练/推理、分拣控制封装，业务循环只出现在类内，入口脚本只做装配 |
| 入口脚本 | `scripts/` | 组装业务动作，包含 `main()` 与 `if __name__ == '__main__'` |
| 测试 | `tests/` | 每个模块一个测试文件，用替身替代真实网络；训练/推理测试用小图 + CPU |
| 运行时产物 | `dataset/`、`dataset_split/`、`pre_model/`、`model/` | 采集数据、划分结果、预训练权重、训练与推理输出，均不提交仓库 |

---

## 2. 环境准备

```powershell
# 建议使用虚拟环境；本项目在 Python 3.12 + paho-mqtt 2.2.0 + torch 2.6.0 下验证
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

依赖分三组：

- MQTT / 采集：`paho-mqtt >= 2.0`（必须 2.x，代码使用 `CallbackAPIVersion.VERSION2` 回调签名）、`numpy >= 1.20`、`opencv-python >= 4.5`；
- 模型训练：`torch >= 2.0`、`torchvision >= 0.15`、`tqdm`、`matplotlib`、`seaborn`、`scikit-learn`、`torchsummary`；
- 测试：`pytest >= 7.0`（`pytest.ini` 用到 `pythonpath` 配置项）。

> 只跑控制脚本时不会 import `torch` / `cv2`（`conveyor/__init__.py` 不导入 `dataset` / `trainer`），因此精简环境下也能控制设备。

GPU 版 PyTorch 建议先按显卡 CUDA 版本单独安装（下面以 CUDA 12.4 为例），再安装其余依赖：

```powershell
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
```

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

# 5) 数据集采集：收设备上报的 base64 图片，存到 dataset/raw（Ctrl+C 退出）
python .\scripts\get_dataset.py

# 6) 数据集划分：按类别随机打乱，8:2 复制到 dataset_split/train 与 dataset_split/valid
python .\scripts\split_dataset.py

# 7) 模型训练：加载 pre_model 下的 ResNet-18 权重，训练/验证并保存 model/best.pth
python .\scripts\train_resnet.py

# 8) 单图推理：加载 model/best.pth，输出类别 / 概率 / 各阶段耗时（图片路径换成实际文件）
python .\scripts\predict_resnet.py --image .\dataset_split\valid\ripe\img1.jpg

# 9) 自动分拣：识别 MQTT 图像并按光电对管推出对应推杆（Ctrl+C 退出）
python .\scripts\sort_conveyor.py
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
| `DATASET_ROOT` / `DATASET_RAW` / `DATASET_RIPE` / `DATASET_HALF_RIPE` | 数据集根目录与三类成熟度目录 |
| `DATASET_CATEGORIES` | 参与划分的类别目录名（`half-ripe` / `raw` / `ripe`） |
| `DATASET_SPLIT_ROOT` / `DATASET_SPLIT_TRAIN` / `DATASET_SPLIT_VALID` | 划分结果目录（`dataset_split/train`、`dataset_split/valid`） |
| `PROP_TRAIN` / `SPLIT_SEED` | 训练集占比（`0.8`）与随机种子（`42`） |
| `PRE_MODEL_DIR` / `MODEL_DIR` | 预训练权重目录（`pre_model/`）与训练输出目录（`model/`） |
| `MODEL_ARCH` / `NUM_CLASSES` | 网络结构（`resnet18`）与分类数（3） |
| `EPOCHS` / `BATCH_SIZE` / `VALID_BATCH_SIZE` | 训练轮数（10）、训练批大小（16）、验证批大小（4） |
| `LEARNING_RATE` / `IMAGE_SIZE` / `NUM_WORKERS` / `SEED` | Adam 学习率（`1e-4`）、输入边长（224）、DataLoader 进程数（0）、随机种子（0） |
| `PREDICT_MODEL` / `PREDICT_RESULT` | 单图推理默认权重（`model/best.pth`）与可视化输出（`model/predict_result.png`） |
| `ROD_LOAD` / `ROD_RIPE` / `ROD_HALF_RIPE` / `ROD_RAW` | 自动分拣推杆序号：上料（`first`）、成熟（`second`）、半熟（`third`）、未熟（`fourth`） |
| `SWITCH_RIPE` / `SWITCH_HALF_RIPE` / `SWITCH_RAW` | 三类对应的光电对管键名（`first_switch` / `second_switch` / `third_switch`） |
| `SWITCH_ACTIVE_VALUE` / `ROD_PUSH_SECS` / `ROD_RELOAD_DELAY_SECS` / `ROD_START_DELAY_SECS` | 对管触发值（`False`）、推杆保持 1 s、补料延时 0.2 s、启动上料延时 0.5 s |
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

## 6. 数据集采集与划分

`scripts/get_dataset.py` 把设备上报的 base64 图片落盘成数据集，供后续训练/评估使用；
`scripts/split_dataset.py` 再把 `dataset/` 按类别随机划分为 `train` 与 `valid`。

### 6.1 报文与保存规则

设备向订阅主题发送（JSON）：

```json
{"image": "<base64 编码的图片字节>"}
```

落盘规则：

- 目录不存在时**自动创建**（默认 `dataset/raw`，已被 `.gitignore` 忽略）；
- 文件名 `img0.jpg`、`img1.jpg` …… 递增；
- 启动时扫描目录里已有的 `img*.jpg`，**从下一个序号继续**，重复运行不会覆盖历史数据；
- 非 `image` 报文（如 `{"conveyor": "run"}`）直接跳过，不占用序号；
- 解码 / 编码 / 写入失败只打印提示并跳过当前报文，接收线程不会退出。

### 6.2 命令行参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--host` | `mqtt.yyzlab.com.cn` | broker 地址 |
| `--port` | 按 `--transport` 取 `9002` / `1883` | broker 端口 |
| `--sub` | `lzm1` | 订阅主题（图片上报） |
| `--pub` | `lzm0` | 发布主题（采集脚本不主动发指令） |
| `--transport` | `wss` | `wss` = WebSocket + TLS；`tcp` = 明文 MQTT |
| `--folder` | `dataset/raw` | 图片保存目录 |

三类成熟度目录已在 `conveyor/config.py` 定义：`DATASET_RAW` / `DATASET_RIPE` / `DATASET_HALF_RIPE`，采集不同批次时用 `--folder` 指定。

### 6.3 运行

```powershell
# 平台默认 wss 9002，保存到 dataset/raw
python .\scripts\get_dataset.py

# 保存到成熟果实目录
python .\scripts\get_dataset.py --folder .\dataset\ripe

# 本地 broker + 明文端口（示例代码里的 127.0.0.1:21883，主题 bb -> aa）
python .\scripts\get_dataset.py --host 127.0.0.1 --port 21883 --transport tcp `
    --sub bb --pub aa --folder .\dataset\raw
```

收到图片时输出：

```text
开始接收图片, 保存目录: D:\...\dataset\raw, 按 Ctrl+C 退出
图片0已保存: D:\...\dataset\raw\img0.jpg
```

按 `Ctrl+C` 停止：脚本会先等接收线程退出，再 `close()` 断开 MQTT。

### 6.4 API：`conveyor.dataset.GetData`

| 成员 | 说明 |
| --- | --- |
| `GetData(mqtt_client, folder_path, image_key="image")` | 创建目录、计算起始序号、启动接收线程 |
| `save_image(image_base64)` | 解码并保存一张图片，成功返回 `Path`，失败返回 `None` |
| `make_dir(folder_path)` | 目录不存在时递归创建 |
| `next_index()` | 扫描 `img*.jpg`，返回下一个可用序号 |
| `close()` | 停止接收线程（`join` 最长 2 s）并关闭 MQTT 连接 |
| `count` / `t_recv_data` / `folder_path` | 当前序号 / 接收线程 / 保存目录 |

```python
from conveyor import config
from conveyor.dataset import GetData

mqtt_client = config.create_client()                 # 已连接并订阅 lzm1
collector = GetData(mqtt_client, config.DATASET_RAW)
try:
    ...                                              # 主线程做别的事，图片由子线程落盘
finally:
    collector.close()
```

### 6.5 与原始示例代码的差异

原始示例在类里自建 `Mqtt_Clt` 并 `while True` 阻塞取队列，整合时做了 5 处调整：

| 原示例 | 本项目 | 原因 |
| --- | --- | --- |
| 类内自建 `Mqtt_Clt` | 由调用方注入 `mqtt_client` | 统一走 `config.create_client()`，wss/TLS 参数不重复，也便于测试替身 |
| `while True` + 阻塞 `get()` | `stop_event` + `get(timeout=0.5)` | 有可控退出点，`close()` 能停线程，进程不会卡死 |
| `cv2.imwrite(path, image)` | `cv2.imencode()` + `Path.write_bytes()` | **Windows 下 `cv2.imwrite` 不支持中文路径**（本项目路径含中文，会静默写失败） |
| `img{i}.jpg` 从 0 开始 | 扫描已有文件续号 | 重复采集不覆盖历史数据 |
| 无异常处理 | 解码 / 编码 / 写入分别捕获并跳过 | 一条坏报文不会终止整个采集线程 |

> `numpy`、`opencv-python` 只在采集时需要；采集产物位于 `dataset/`、划分产物位于 `dataset_split/`，均已被 `.gitignore` 忽略，不会误提交。

### 6.6 数据集划分

`scripts/split_dataset.py` 读取 `dataset/<类别>`，对**每个类别单独随机打乱**后，按 `PROP_TRAIN`（默认 0.8）切分并复制到 `dataset_split/train/<类别>` 与 `dataset_split/valid/<类别>`。

规则：

- **只复制不移动**：`shutil.copy` 复制文件，`dataset/` 源文件保持不变；
- **每类单独切分**：三个类别都按比例划分，不会出现某一类全进训练集；
- 训练集张数 = `int(类别总数 × PROP_TRAIN)`，验证集自动取剩余 20%；
- **默认先清空 `dataset_split/`**：避免上次划分的旧文件残留，导致同一张图同时出现在 train 与 valid（数据泄漏）；需要保留时加 `--keep`；
- 源目录 / 类别目录缺失、类别目录为空、占比不在 0~1 之间、目标目录与源目录重叠时**直接报错**，不会留下划分了一半的结果；
- 固定 `SPLIT_SEED = 42` 时，同一份数据重复划分结果一致；`--seed -1` 则每次随机。

当前 753 张数据的划分结果：

```text
half-ripe: train 200 张, valid 51 张
raw: train 200 张, valid 51 张
ripe: train 200 张, valid 51 张
数据集划分完成, 输出目录: D:\...\dataset_split
```

### 6.7 命令行参数与运行

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--source` | `dataset` | 源数据集根目录（其下按类别分文件夹） |
| `--target` | `dataset_split` | 划分结果根目录 |
| `--prop-train` | `0.8` | 训练集占比（0~1），验证集自动取剩余部分 |
| `--seed` | `42` | 随机种子；`-1` 表示每次随机 |
| `--keep` | 关闭 | 保留目标目录已有文件（默认先清空） |

```powershell
# 默认：dataset -> dataset_split，8:2，种子 42（结果可复现）
python .\scripts\split_dataset.py

# 自定义占比与输出目录，每次随机打乱
python .\scripts\split_dataset.py --prop-train 0.7 --target .\dataset_70 --seed -1

# 保留目标目录已有文件（不清空）
python .\scripts\split_dataset.py --keep
```

常改的参数也可以直接改 `conveyor/config.py` 里的 `PROP_TRAIN` / `DATASET_SPLIT_ROOT` / `SPLIT_SEED` / `DATASET_CATEGORIES`。

### 6.8 API：`conveyor.dataset_split.SplitDataset`

| 成员 | 说明 |
| --- | --- |
| `SplitDataset(source_dir, target_dir, categories=None, prop_train=0.8, seed=42, clean=True)` | 记录划分参数；`categories` 默认取 `config.DATASET_CATEGORIES` |
| `run()` | 校验 → 清空/创建目标目录 → 逐类划分，返回 `{"raw": {"train": 200, "valid": 51}, ...}` |
| `split_category(category)` | 单类别打乱 + 切分 + 复制，返回该类别数量 |
| `list_images(folder_path)` | 列出目录内文件名（忽略子目录），排序后再打乱以保证可复现 |
| `copy_images(images, src_dir, dst_dir)` | 逐个 `shutil.copy`，同名覆盖，源文件不变 |
| `summary` | 最近一次 `run()` 的各类别 train / valid 数量 |

```python
from conveyor import config
from conveyor.dataset_split import SplitDataset

splitter = SplitDataset(prop_train=config.PROP_TRAIN, seed=config.SPLIT_SEED)
summary = splitter.run()
```

## 7. 模型训练（ResNet）

`conveyor/resnet.py` 定义网络，`conveyor/trainer.py` 封装训练/验证/评估，`scripts/train_resnet.py` 是命令行入口。
数据来自第 6 节划分出的 `dataset_split/train` 与 `dataset_split/valid`，预训练权重放在 `pre_model/`。

### 7.1 网络结构

| 名称 | 说明 |
| --- | --- |
| `BasicBlock` | ResNet-18/34 的基础残差块：两层 3x3 卷积 + shortcut，`expansion = 1` |
| `Bottleneck` | ResNet-50 的瓶颈残差块：1x1 → 3x3 → 1x1，`expansion = 4` |
| `ResNet` | 主干（conv1 + 4 个 stage）+ 全局平均池化 + 全连接分类头 |
| `resnet18/34/50(num_classes=1000)` | 三个标准结构，分类数可改 |
| `create_resnet(arch, num_classes)` | 按名称创建，`arch` 仅支持 `resnet18/34/50` |
| `load_pretrained(model, weight_path)` | 严格加载 ImageNet 权重；文件不存在时打印提示并返回 `False` |

Bottleneck 采用 **ResNet v1.5** 写法：第一个 1x1 卷积步距为 1，由 3x3 卷积承担 `stride`。
训练时先构建 1000 类模型加载 ImageNet 权重，再把 `model.fc` 替换为 `nn.Linear(512 * expansion, 3)`，输出三类成熟度。

### 7.2 预训练权重

| 结构 | 文件名 | 官方地址 |
| --- | --- | --- |
| ResNet-18 | `resnet18-f37072fd.pth` | <https://download.pytorch.org/models/resnet18-f37072fd.pth> |
| ResNet-34 | `resnet34-333f7ec4.pth` | <https://download.pytorch.org/models/resnet34-333f7ec4.pth> |
| ResNet-50 | `resnet50-19c8e357.pth` | <https://download.pytorch.org/models/resnet50-19c8e357.pth> |

```powershell
# 以 ResNet-18 为例，保存到 pre_model/resnet18-f37072fd.pth
Invoke-WebRequest -Uri https://download.pytorch.org/models/resnet18-f37072fd.pth `
    -OutFile .\pre_model\resnet18-f37072fd.pth
```

- 文件名与 `conveyor/resnet.py` 的 `PRETRAINED_WEIGHTS` 一一对应；
- `pre_model/` 已被 `.gitignore` 忽略，换机器时需重新下载或拷贝；
- 权重缺失时训练不会中断，会打印“预训练权重不存在, 使用随机初始化”后从零训练；
- 需要显式从零训练时加 `--no-pretrained`，不读取权重文件。

### 7.3 训练与验证流程

1. `setup_seed(SEED)` 固定 Python / Numpy / PyTorch / CUDA 种子，并设置 cudnn 为确定性算法；
2. 训练集：`RandomResizedCrop(224)` + `RandomHorizontalFlip` + `ToTensor` + ImageNet 均值方差归一化；
3. 验证集：`Resize((224, 224))` + `ToTensor` + 同样的归一化；
4. 损失函数 `CrossEntropyLoss`，优化器 `Adam(lr=1e-4)`；
5. 每个 epoch 训练后验证；验证准确率**严格高于历史最优**时保存 `model/best.pth`，每轮结束保存 `model/last.pth`；
6. 训练结束后载入 `best.pth`，在验证集上计算最终准确率，并用 seaborn 绘制混淆矩阵到 `model/confusion_matrix.png`。

指标按样本数平均：`loss = 累计 loss / 数据集张数`，`acc = 预测正确数 / 数据集张数`。

### 7.4 命令行参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--data-root` | `dataset_split` | 划分后的数据集根目录（其下含 `train/`、`valid/`） |
| `--pre-model` | `pre_model` | ImageNet 预训练权重目录 |
| `--model-dir` | `model` | 输出目录（`best.pth` / `last.pth` / 混淆矩阵） |
| `--arch` | `resnet18` | `resnet18` / `resnet34` / `resnet50` |
| `--epochs` | `10` | 训练轮数 |
| `--batch-size` | `16` | 训练批大小 |
| `--valid-batch-size` | `4` | 验证批大小 |
| `--lr` | `0.0001` | Adam 学习率 |
| `--image-size` | `224` | 输入图片边长 |
| `--num-workers` | `0` | DataLoader 进程数（Windows 建议 0） |
| `--seed` | `0` | 全局随机种子 |
| `--device` | `auto` | `auto` / `cpu` / `cuda`，默认有 GPU 用 GPU |
| `--no-pretrained` | 关闭 | 不加载预训练权重，从随机初始化开始训练 |

### 7.5 运行与输出

```powershell
# 先完成数据集划分（第 6 节），再训练
python .\scripts\split_dataset.py
python .\scripts\train_resnet.py

# 换 ResNet-34、20 轮、指定 GPU
python .\scripts\train_resnet.py --arch resnet34 --epochs 20 --device cuda

# 小图快速联调（不加载预训练）
python .\scripts\train_resnet.py --image-size 64 --epochs 1 --batch-size 4 --no-pretrained
```

训练完成后输出：

```text
训练完成, 验证集准确率: 100.00%
最优模型: D:\...\model\best.pth
混淆矩阵: D:\...\model\confusion_matrix.png
```

### 7.6 当前训练结果

当前 `dataset_split/` 共 753 张（train 600 / valid 153），ResNet-18 + ImageNet 预训练，Adam `1e-4`，batch 16，输入 224，CPU 训练 10 轮：

| epoch | train_loss | train_acc | val_loss | val_acc |
| --- | --- | --- | --- | --- |
| 1 | 0.021 | 0.862 | 0.028 | 0.954 |
| 2 | 0.010 | 0.938 | 0.004 | **1.000** |
| 3 | 0.005 | 0.967 | 0.003 | 1.000 |
| 4 | 0.004 | 0.978 | 0.004 | 1.000 |
| 5 | 0.006 | 0.960 | 0.001 | 1.000 |
| 6 | 0.005 | 0.968 | 0.001 | 1.000 |
| 7 | 0.005 | 0.970 | 0.000 | 1.000 |
| 8 | 0.003 | 0.977 | 0.000 | 1.000 |
| 9 | 0.004 | 0.977 | 0.000 | 1.000 |
| 10 | 0.003 | 0.987 | 0.000 | 1.000 |

- 最优模型出现在第 2 轮（`val_acc = 1.000`），最终载入 `best.pth` 复评，153 张验证图全部预测正确；
- 混淆矩阵对角线为 51 / 51 / 51，保存于 `model/confusion_matrix.png`；
- CPU（torch 2.6.0+cpu）单轮约 40 秒，10 轮数分钟完成；使用 CUDA 会更快。

> 验证集只有 153 张且与训练集同批次采集，100% 准确率只说明当前数据可分，**不代表跨批次泛化能力**；上线前应补充新批次数据复测。

### 7.7 API：`conveyor.trainer.ResNetTrainer`

| 成员 | 说明 |
| --- | --- |
| `ResNetTrainer(data_root, pre_model_dir, model_dir, arch, epochs, batch_size, valid_batch_size, lr, image_size, num_workers, seed, device=None, pretrained=True, verbose=True)` | 记录训练参数；`device=None` 时自动选择 GPU/CPU |
| `setup()` | 固定种子，构建数据集、DataLoader、模型、损失函数与优化器 |
| `build_model(num_classes)` | 创建 ResNet、加载预训练权重、替换 `fc` 并移到设备 |
| `fit()` | 逐轮训练/验证并保存 `best.pth`、`last.pth`，返回每轮指标列表 |
| `evaluate(load_best=True)` | 载入最优模型，返回 `accuracy` / `confusion_matrix` / 标签 |
| `run()` | 完整流程，返回训练历史、准确率、模型路径与混淆矩阵路径 |

```python
from conveyor import config
from conveyor.trainer import ResNetTrainer

trainer = ResNetTrainer(epochs=10, device="cuda", pretrained=True)
result = trainer.run()
print(result["accuracy"], result["best_model"])
```

## 8. 单图推理（ResNet）

`conveyor/profile.py` 提供计时器 `Profile`，`conveyor/predictor.py` 封装 `ResNetPredictor`，`scripts/predict_resnet.py` 是命令行入口。整体流程与原始示例一致：**加载权重 → 预处理 → 预热 → 推理 → 可视化**。

### 8.1 推理流程

| 步骤 | 实现 | 说明 |
| --- | --- | --- |
| 1. 加载模型 | `create_resnet(arch, num_classes)` + `load_state_dict` + `eval()` | 权重缺失直接抛 `FileNotFoundError`，不会用随机初始化“假装”推理 |
| 2. 预处理 | `Path.read_bytes` + `cv2.imdecode` → BGR 转 RGB → `ToPILImage` + `Resize(image_size)` + `ToTensor` + ImageNet 归一化 → `unsqueeze(0)` | 用 `imdecode` 而非 `imread`，兼容 Windows 中文路径；MQTT 报文走 `predict_base64()`，无需落盘 |
| 3. 预热 | 全零 `(1, 3, image_size, image_size)` 输入跑一次 | 把首次推理的内存分配 / 算子加载开销排除在计时之外，只做一次 |
| 4. 推理 | `eval()` + `torch.no_grad()`，softmax 后 `torch.max` | 不建计算图，固定 BN 统计量 |
| 5. 可视化 | matplotlib 显示原图，标题为 `Predicted class: xxx, probability: xxx` | 默认保存 `model/predict_result.png`，`--no-show` 不弹窗 |

计时使用 `Profile`（CUDA 可用时先 `synchronize()` 再取时间戳），输出加载模型 / 预处理 / 预热 / 推理四段耗时（毫秒）。

> 类别顺序必须与训练时 `ImageFolder` 的目录升序一致，项目为 `half-ripe → raw → ripe`（对应 `config.DATASET_CATEGORIES`）。顺序错了，概率正确但类别名会错位。

### 8.2 命令行参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--image` | **必填** | 待推理图片路径，支持中文路径 |
| `--model` | `model/best.pth` | 模型权重路径 |
| `--arch` | `resnet18` | `resnet18` / `resnet34` / `resnet50`，需与训练时一致 |
| `--image-size` | `224` | 输入图片边长，需与训练时一致 |
| `--classes` | `half-ripe raw ripe` | 类别名称，顺序需与训练时一致，个数需等于分类数 |
| `--output` | `model/predict_result.png` | 可视化结果保存路径 |
| `--device` | `auto` | `auto` / `cpu` / `cuda`，默认有 GPU 用 GPU |
| `--no-show` | 关闭 | 只保存可视化图片，不弹窗显示 |

### 8.3 运行与输出

```powershell
# 用 model/best.pth 推理一张验证集图片（弹窗显示并保存可视化结果）
python .\scripts\predict_resnet.py --image .\dataset_split\valid\ripe\img1.jpg

# 无界面环境 / 远程服务器：只保存图片
python .\scripts\predict_resnet.py --image .\dataset_split\valid\raw\img1.jpg --no-show

# 换 ResNet-34 权重与自定义类别顺序
python .\scripts\predict_resnet.py --image test.jpg --model .\model\resnet34.pth `
    --arch resnet34 --classes half-ripe raw ripe --device cuda
```

输出示例：

```text
已加载模型: D:\...\model\best.pth, 设备: cpu
预测类别: ripe, 概率: 0.9999
图片尺寸: (1, 3, 224, 224), 加载模型: 94.2ms, 预处理: 7.9ms, 预热: 8.6ms, 推理: 8.2ms
可视化结果: D:\...\model\predict_result.png
```

> 首次调用包含加载模型与预热，耗时明显高于后续调用；批量 / 循环推理时应复用同一个 `ResNetPredictor` 实例。

### 8.4 API：`conveyor.predictor.ResNetPredictor`

| 成员 | 说明 |
| --- | --- |
| `ResNetPredictor(model_path, arch, num_classes, image_size, class_names=None, device=None, result_path=..., verbose=True)` | 记录推理参数；`class_names` 默认取 `config.DATASET_CATEGORIES`，个数必须等于 `num_classes` |
| `load_model()` | 创建 ResNet、加载权重、`eval()` 并记录加载耗时，返回模型 |
| `read_image(image_path)` | 读图并转 RGB（`Path.read_bytes` + `cv2.imdecode`，兼容中文路径） |
| `decode_image(image_data, source="<bytes>")` | 图片字节 → RGB ndarray（base64 解码后的数据可直接传入） |
| `predict_image(image)` | 对已解码的 RGB ndarray 推理，不落盘 |
| `predict_base64(image_base64)` | 对 MQTT 报文里的 base64 图片推理，不落盘 |
| `preprocess(image)` | `ToPILImage + Resize + ToTensor + Normalize`，补批次并移到设备 |
| `warmup()` | 全零输入预热一次 |
| `predict(image_path)` | 返回 `class_index` / `class_name` / `probability` / `probabilities` / `image` / `input_shape` / `timings` |
| `save_visualization(image, result, save_path=None, show=False)` | 保存并可选显示可视化图片，返回保存路径 |

```python
from conveyor.predictor import ResNetPredictor

predictor = ResNetPredictor(device="cuda")
result = predictor.predict("./dataset_split/valid/ripe/img1.jpg")
print(result["class_name"], result["probability"], result["timings"])
predictor.save_visualization(result["image"], result, show=True)
```

## 9. 自动分拣主程序

`conveyor/sorter.py` 封装 `ConveyorSorter`，`scripts/sort_conveyor.py` 是主程序入口。它把前面几节串成闭环：**加载权重 → 连接平台 → 收图像报文并识别 → 按光电对管触发推杆 → 延时补料**。

### 9.1 控制流程

| 步骤 | 触发 | 动作 |
| --- | --- | --- |
| 1. 启动 | `sorter.run()` → `start()` | 下发 `{"conveyor": "run"}`、`{"rod_control": "all_pull"}`，0.5 s 后推出上料推杆 `first` |
| 2. 识别 | 报文含 `image` | `predict_base64()` 解码 + 推理，记录当前类别（`ripe` / `half-ripe` / `raw`） |
| 3. 分拣 | 对管键匹配当前类别 | 立即推出对应分拣推杆，0.2 s 后推出 `first` 补料 |
| 4. 复位 | 推杆推出 1 s 后 | 自动下发 `<rod>_pull` |
| 5. 退出 | Ctrl+C / 异常 | 取消未执行定时器，等待执行中的推杆拉回，停传送带，关 MQTT |

推杆与对管映射（均可在 `conveyor/config.py` 修改）：

| 类别 | 分拣推杆 | 光电对管 | 默认触发值 |
| --- | --- | --- | --- |
| `ripe` | `second` | `first_switch` | `False` |
| `half-ripe` | `third` | `second_switch` | `False` |
| `raw` | `fourth` | `third_switch` | `False` |
| 上料 | `first` | — | — |

> 示例设备在遮挡时上报 `{"first_switch": false}`（低电平有效），因此默认 `switch_active_value=False`。若实际设备为高电平有效，用 `--switch-value true` 或构造参数 `switch_active_value=True`。

识别和动作都在主循环 / 定时器线程中执行：坏图片只跳过当前报文，单个推杆指令失败也不会中断分拣；推杆推出后在新线程里等待 1 s 再拉回，不阻塞后续图像识别。

### 9.2 命令行参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--host` / `--port` | 平台 / 按传输方式 | broker 地址与端口；本地调试可传 `127.0.0.1` / `21883` |
| `--sub` / `--pub` | `lzm1` / `lzm0` | 订阅设备上报、发布控制指令 |
| `--transport` | `wss` | `wss`（平台 9002）或 `tcp`（明文 1883 / 本地 broker） |
| `--model` | `model/best.pth` | 模型权重；缺失时启动即报错，不会连接平台 |
| `--arch` | `resnet18` | `resnet18` / `resnet34` / `resnet50`，需与训练时一致 |
| `--image-size` | `224` | 输入边长，需与训练时一致 |
| `--classes` | `half-ripe raw ripe` | 类别顺序，需与训练时 `ImageFolder` 一致 |
| `--device` | `auto` | `auto` / `cpu` / `cuda` |
| `--switch-value` | `false` | 对管触发时的上报值，`false` / `true` |

### 9.3 运行与输出

```powershell
# 平台默认 wss 9002 + model/best.pth
python .\scripts\sort_conveyor.py

# 本地 broker + 明文端口（示例代码里的 127.0.0.1:21883，主题 bb -> aa）
python .\scripts\sort_conveyor.py --transport tcp --host 127.0.0.1 --port 21883 `
    --sub bb --pub aa

# 换权重、CPU 推理、对管高电平有效
python .\scripts\sort_conveyor.py --model .\model\last.pth --device cpu --switch-value true
```

输出示例：

```text
已加载模型: D:\...\model\best.pth, 设备: cpu
MQTT连接成功, 已订阅主题 lzm1
下发指令: conveyor=run -> 主题 lzm0
下发指令: rod_control=all_pull -> 主题 lzm0
开始分拣, 按 Ctrl+C 退出
识别结果: ripe, 概率: 0.9999, 推理耗时: 8.3ms
对管 first_switch 触发, 类别 ripe -> 推杆 second
下发指令: rod_control=second_push -> 主题 lzm0
下发指令: rod_control=first_push -> 主题 lzm0
下发指令: rod_control=second_pull -> 主题 lzm0
下发指令: rod_control=first_pull -> 主题 lzm0
程序退出, 关闭mqtt
下发指令: conveyor=stop -> 主题 lzm0
```

> 同一时间只跟踪**最近一帧图像的类别**（与示例代码一致）。设备需要保证“先上报图像、后上报对管”的顺序；图像与对管不是一一对应时，可能用旧类别触发推杆。

### 9.4 API：`conveyor.sorter.ConveyorSorter`

| 成员 | 说明 |
| --- | --- |
| `ConveyorSorter(mqtt_client, predictor=None, load_rod="first", class_rods=None, switch_classes=None, push_secs=1.0, reload_delay=0.2, start_delay=0.5, switch_active_value=False, verbose=True)` | 记录设备映射与动作延时；`predictor` 不传时自动创建 `ResNetPredictor` |
| `start()` | 传送带运行 + 所有推杆拉回 + 延时推出上料推杆 |
| `run(poll_secs=0.5)` | 启动设备并循环消费 `mqtt_client.mqtt_queue`，直到 `close()` / Ctrl+C |
| `handle_message(msg)` | 图像报文转 `identify()`，其他报文转 `handle_switch()` |
| `identify(image_base64)` | base64 解码 + 推理，成功时更新 `current_class`；失败返回 `None` 并保留上一次类别 |
| `handle_switch(msg)` | 对管键与当前类别同时匹配时，调度分拣推杆和补料推杆 |
| `push_pull(rod)` | 推出推杆 → 保持 `push_secs` → 拉回 |
| `schedule(delay, rod)` | 用 daemon `threading.Timer` 延时执行 `push_pull`，返回定时器 |
| `close()` | 取消未执行定时器、等待执行中的推杆复位、下发 `conveyor=stop`、关闭 MQTT |
| `current_class` | 最近一次识别出的类别，未被识别前为 `None` |

```python
from conveyor import config
from conveyor.predictor import ResNetPredictor
from conveyor.sorter import ConveyorSorter

mqtt_client = config.create_client()
predictor = ResNetPredictor(device="cuda")
predictor.load_model()
sorter = ConveyorSorter(mqtt_client, predictor)
try:
    sorter.run()
finally:
    sorter.close()
```

## 10. 测试

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
| `test_config.py` | 常量取值正确；`create_client` 的参数映射（wss/明文、TLS 跟随、主题与 client_id 透传）；训练目录与超参数 |
| `test_mqtt_client.py` | 传输与 TLS 选项、CONNACK 等待、超时/拒绝异常、on_connect 订阅、client_id 唯一性、JSON 发布参数与确认、消息解析/队列满/解析失败、断线与关闭顺序 |
| `test_control_conveyor.py` | 下发 `conveyor=stop`、送达/未送达提示、异常时仍关闭连接、"结束"输出 |
| `test_control_rod_control.py` | 先 `conveyor=run` 再 `rod_control=first_push`、Ctrl+C 退出与关闭 |
| `test_recv_msg.py` | 收报打印与线程退出、动作下发顺序、Ctrl+C 清理 |
| `test_pub_mqtt.py` | 原生客户端 wss 配置、连接回调输出、发布参数与等待确认、断开顺序 |
| `test_sub_mqtt.py` | 订阅 `lzm1`、连接失败不订阅、消息打印、`loop_forever` 中断后断开 |
| `test_dataset.py` | 目录创建/复用、序号续接、base64 解码落盘、非图像报文跳过、坏数据/编码/写入失败、线程收发与关闭、真实 opencv 往返 |
| `test_dataset_split.py` | 配置默认值、按类别 8:2 切分与源文件不变、打乱/种子复现、清空与 `--keep`、缺类/空类/非法占比/目录重叠校验 |
| `test_resnet.py` | BasicBlock/Bottleneck 的 `expansion`、ResNet v1.5 步距、18/34/50 结构与前向输出、`create_resnet` 非法结构、权重文件映射、缺失权重回退、state_dict 存取往返 |
| `test_trainer.py` | ImageFolder/DataLoader 装配、类别一致性校验、预训练权重路径、固定种子复现、CPU 小图完整训练并检查 best/last/混淆矩阵、评估准确率 |
| `test_profile.py` | 单次/多次累加计时、初始耗时、作为装饰器使用 |
| `test_predictor.py` | 默认参数、类别数与名称校验、权重缺失报错、`eval()` 与加载计时、BGR→RGB、`decode_image` 字节解码/非法数据、Resize 后张量形状、`predict` / `predict_image` / `predict_base64` 三种入口、概率和、复用模型只预热一次、中文路径读图、可视化落盘 |
| `test_get_dataset.py` | 默认参数、命令行覆盖（本地 broker/tcp）、`create_client` 装配、Ctrl+C 与异常时关闭采集器 |
| `test_split_dataset.py` | 默认与自定义命令行参数、`SplitDataset` 装配、`--seed -1` 与 `--keep` 映射 |
| `test_train_resnet.py` | 默认/自定义命令行参数、`ResNetTrainer` 装配、`auto` 设备与 `--no-pretrained` 映射 |
| `test_predict_resnet.py` | 默认/自定义命令行参数、`--image` 必填、耗时格式化、`ResNetPredictor` 装配、`auto` 设备与 `--no-show` 映射 |
| `test_sorter.py` | 默认推杆/对管映射、类别缺少推杆校验、启动指令与上料定时、push→等待→pull 时序、识别成功/失败隔离、对管触发值（`False` / `True` 可配）、类别不匹配不动作、消息路由、主循环消费与关闭、close 取消定时器/停传送带/关 MQTT |
| `test_sort_main.py` | 默认/自定义命令行参数、`create_client` / `ResNetPredictor` / `ConveyorSorter` 装配、`--switch-value` 映射、Ctrl+C 与异常关闭、权重缺失时不连接平台 |

当前结果：**154 passed**。

> 训练 / 推理相关测试使用 3 类合成小图和随机初始化的 ResNet-18 权重，在 CPU 上完成 1 个 epoch 训练或单图前向，**不需要 GPU、真实数据集或网络**。

> 测试替身只模拟行为、不校验真实 broker 语义；真实链路仍需用 `control_conveyor.py` + MQTTX 联合验证。

---

## 11. MQTTX 客户端配置

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

## 12. 故障排查

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
| 采集脚本一直收不到图片 | 设备未上报，或报文里没有 `image` 键 | 先用 `python .\scripts\sub_mqtt.py` 看 `lzm1` 原始报文，确认键名与 base64 内容 |
| 提示"图片解码失败, 已跳过该报文" | base64 解出来不是图片（如 URL、纯文本、二次编码） | 让设备端先 JPEG/PNG 编码再 base64，只编码一次 |
| 采集图片不全 / 频繁"消息队列满" | 图片体积大、落盘慢，`queue.Queue(5)` 溢出 | 降低设备推送频率，或调大 `Mqtt_Clt` 的队列容量（会占更多内存） |
| 报错"源数据集缺少类别目录" | `dataset/` 下三类目录不全 | 补齐 `dataset/raw`、`dataset/ripe`、`dataset/half-ripe` 后再划分 |
| `ModuleNotFoundError: No module named 'torch'` | 只装了 MQTT/采集依赖，未装训练依赖 | `pip install -r requirements.txt`；GPU 版按第 2 节用 cu124 源单独安装 |
| 训练日志提示“预训练权重不存在, 使用随机初始化” | `pre_model/` 下没有对应文件或文件名不符 | 按 7.2 节下载到 `pre_model/resnet18-f37072fd.pth`；确认 `--arch` 与文件名匹配 |
| 加载权重报 `size mismatch for fc.weight` | 权重不是官方 1000 类 ImageNet 权重 | 使用 7.2 节的官方权重；或加 `--no-pretrained` 从零训练 |
| `--device cuda` 报 `Torch not compiled with CUDA enabled` | 安装的是 CPU 版 torch | 按第 2 节安装 CUDA 轮子，或改用 `--device cpu` |
| CUDA out of memory | batch 太大或显存被其他进程占用 | 降低 `--batch-size`（如 8/4）或 `--image-size`，关闭占用显存的程序 |
| 训练很慢 | 用 CPU 训练、`num_workers=0`、图片被放大到 224 | 优先用 GPU；Windows 下可试 `--num-workers 2`；小图联调可 `--image-size 64` |
| 报错“train 与 valid 类别不一致” | 两次划分使用了不同类别集合，或手工增删了类别目录 | 重新执行 `python .\scripts\split_dataset.py`，确保两边目录完全一致 |
| train / valid 中出现同名图片 | 上一次划分的旧文件残留，或用了 `--keep` 追加不同批次 | 默认会清空 `dataset_split/`；跨批次划分时不要用 `--keep` |
| 单图推理报“模型文件不存在” | `model/best.pth` 未生成或 `--model` 路径写错 | 先跑 `python .\scripts\train_resnet.py`，或用 `--model` 指定已有权重 |
| 推理类别与肉眼不符 | `--classes` 顺序与训练目录排序不一致，或 `--arch` / `--image-size` 与训练不符 | 保持默认 `half-ripe raw ripe`；`--arch`、`--image-size` 与训练命令一致 |
| 加载推理权重报 `size mismatch` | `--classes` 个数与训练时分类数不一致 | `--classes` 个数必须等于训练时的 `NUM_CLASSES`（默认 3） |
| 推理后没有弹窗 | 无界面 / 远程会话，或加了 `--no-show` | 图片已保存到 `--output`，属正常行为 |
| 自动分拣启动即报“模型文件不存在” | 权重未生成或 `--model` 路径写错 | 先训练 `model/best.pth`，或用 `--model` 指定；主程序在连接平台前就会退出 |
| 对管位置到了但推杆不动 | 当前类别与对管不匹配、对管键名不符，或触发值与设备电平相反 | 用 `sub_mqtt.py` 看 `lzm1` 对管报文；核对 `config.SWITCH_*`；低电平用默认 `false`，高电平加 `--switch-value true` |
| 一张图后连续推多次 | 设备持续上报同一对管状态，分拣按报文触发且无去抖 / 边沿检测 | 让设备只在状态变化时上报；或在设备侧 / 上位机增加去抖（当前未实现） |
| 分拣时推错类别 | 图像未先于对管到达，使用了上一帧的 `current_class` | 检查上报顺序与图像 / 对管是否一一对应；必要时在设备侧保证先图后对管 |
| Ctrl+C 后设备仍在运行 | 停止指令未送达或程序异常退出 | 正常退出会先取消定时器、等推杆拉回再发 `conveyor=stop`；若提示停止失败，人工断电确认 |
| 分拣识别明显变慢 | CPU 推理、图片过大，或每帧重复加载模型 | 用 GPU；`--image-size` 与训练一致；`ConveyorSorter` 默认复用同一个 `ResNetPredictor`，只加载 / 预热一次 |

自检顺序（推荐）：

1. `python .\scripts\control_conveyor.py` —— 能打印"MQTT连接成功"和"结束"，说明链路与 TLS 正常；
2. MQTTX 订阅 `lzm0`，再跑一次 —— 应看到 `{"conveyor": "stop"}`（注意可能有一条旧的重试报文）；
3. `python .\scripts\sub_mqtt.py` 观察 `lzm1` —— 有上报说明设备在线，可继续测试 `run` / `first_push`；
4. 设备无任何上报时，问题在设备侧（在线状态、broker 地址、端口协议），与上位机脚本无关。

模型训练自检：

1. `python -m pytest tests\test_resnet.py tests\test_trainer.py` —— 不依赖 GPU / 真实数据，先确认网络与训练流程正常；
2. `python .\scripts\train_resnet.py --epochs 1` —— 观察是否打印“已加载预训练权重”并生成 `model/best.pth`；
3. 查看 `model/confusion_matrix.png`，三类若严重偏向某一类，优先检查数据集类别是否均衡、标签目录是否放错。

单图推理自检：

1. `python -m pytest tests\test_profile.py tests\test_predictor.py tests\test_predict_resnet.py` —— 用随机权重的 ResNet-18 验证推理链路；
2. `python .\scripts\predict_resnet.py --image <一张验证集图片> --no-show` —— 应打印“已加载模型”“预测类别”“各阶段耗时”，并生成 `model/predict_result.png`；
3. 若预测类别与图片不符，先确认 `--arch` / `--image-size` / `--classes` 与训练时一致，再怀疑模型本身。

自动分拣自检：

1. `python -m pytest tests\test_sorter.py tests\test_sort_main.py tests\test_predictor.py` —— 验证推杆映射、动作时序、主程序装配与推理入口；
2. 先按单图推理自检确认 `model/best.pth` 能正确识别；
3. `python .\scripts\sort_conveyor.py --transport tcp --host 127.0.0.1 --port 21883 --sub bb --pub aa` 连本地 broker，MQTTX 同时订阅 `bb` / `aa` 观察图像与对管报文；
4. 手动发一条对管报文（值需与 `--switch-value` 一致），确认对应推杆先推后拉、0.2 s 后补料；若不对，先核对 `first/second/third/fourth` 与现场接线。

---

## 13. 设计要点与已知限制

设计要点：

- **订阅位置**：`subscribe()` 写在 `on_connect` 回调内，重连后自动恢复；写在 `__init__` 里只在首次生效。
- **发布确认**：`wait_for_publish()` 只是确认"broker 收到"，不代表"设备执行"；设备执行结果必须看 `lzm1` 上报。
- **关闭顺序**：`disconnect()` → `loop_stop()`，先发 DISCONNECT 让 broker 正常清理会话，再停网络线程。
- **队列解耦**：`on_message` 只做解析入队，业务线程通过 `mqtt_queue` 消费，避免阻塞 paho 网络线程。
- **唯一 client_id**：避免同 ID 客户端互踢，导致"时而收得到、时而收不到"。
- **采集线程**：`GetData` 用 daemon 线程 + `stop_event` 消费 `mqtt_queue`，`close()` 先停线程再断 MQTT，避免写出半张图片。
- **可复现划分**：`SplitDataset` 用独立的 `random.Random(seed)` 打乱，固定种子即可复现同一份 train / valid；默认先清空输出目录，避免旧文件残留造成训练/验证数据泄漏。
- **预训练 + 换头**：ResNet 先按 1000 类加载 ImageNet 权重，再把 `fc` 换成 3 类线性层，既复用特征又避免类别数不匹配。
- **保存策略**：第一轮无条件保存 `best.pth`（初始最优值设为 `-1`），之后仅当验证准确率严格提升才覆盖；每轮都更新 `last.pth`，便于对比过拟合。
- **可复现训练**：`setup_seed()` 同时固定 Python / Numpy / PyTorch / CUDA 种子，并设置 cudnn deterministic；DataLoader 训练集打乱、验证集保持顺序。
- **验证集预处理**：只做 `Resize + Normalize`，不引入随机裁剪/翻转，保证每轮评估口径一致。
- **产物隔离**：`pre_model/`、`model/` 与数据集一样被 `.gitignore` 忽略，仓库只保留代码与权重下载地址。
- **中文路径**：图片落盘用 `cv2.imencode()` + `Path.write_bytes()`，读取用 `Path.read_bytes` + `cv2.imdecode()`；`cv2.imwrite()` / `cv2.imread()` 在 Windows 中文路径下会静默失败。
- **推理权重严格加载**：单图推理的 `best.pth` 不存在时直接抛 `FileNotFoundError`，不像训练时那样回退随机初始化，避免用未训练权重输出“看似正常”的预测。
- **预热只做一次**：`ResNetPredictor` 用 `warmed_up` 标记，只有首次 `predict()` 会执行预热；复用同一实例循环推理时，计时只反映预处理与前向。
- **推理阶段不计梯度**：`eval()` + `torch.no_grad()`，固定 BN 统计量并降低显存占用。
- **类别顺序一致**：`class_names` 默认取 `config.DATASET_CATEGORIES`，必须与训练时 `ImageFolder` 的目录升序（`half-ripe` / `raw` / `ripe`）一致，否则类别名会错位。
- **计时口径统一**：加载模型 / 预处理 / 预热 / 推理四段全部用 `Profile` 测量；CUDA 可用时先 `synchronize()`，避免测到异步下发耗时。
- **分拣映射集中**：推杆序号、对管键名、触发值和动作延时全部放在 `config.py`，`ConveyorSorter` 只接收映射，换接线无需改业务代码。
- **对管按配置值触发**：只匹配“键存在且值等于 `switch_active_value`”的报文，不比较整个字典；同一报文带多个状态键时也不会误判。
- **推杆定时器可取消**：每个 `threading.Timer` 都是 daemon 并登记在集合里；`close()` 先 `cancel()`，再等待正在执行的推杆拉回，避免退出时停在推出状态。
- **分拣故障隔离**：图片解码 / 推理失败只跳过当前帧并保留上一次类别；单个推杆指令失败只记录日志，主循环继续消费报文。
- **启动前置校验**：主程序先 `load_model()` 再连接平台，权重缺失时设备不会被启动；正常退出统一走 `close()` 停传送带并关闭 MQTT。

已知限制：

- 未实现持久会话（`clean_session=False` / `session_expiry`），断线期间下发的 QoS1 报文不会补发；
- `retain` 默认关闭，指令不会被 broker 保留给后上线的设备（旧用例中 `lzm0` 存在一条历史 retained 报文，测试时可能先收到它）；
- 未做 TLS 证书固定（pinning）与双向认证，仅依赖系统 CA 校验服务端证书；
- 设备侧行为（是否执行、执行结果）不在本仓库范围内，需结合设备固件与平台日志排查；
- 训练只支持单标签三分类与固定输入尺寸，未实现早停、学习率调度、混合精度、k 折交叉验证；
- 当前验证集与训练集同批次采集且仅 153 张，100% 准确率不代表跨批次泛化能力；
- 自动分拣已支持 MQTT 图像 + 光电对管闭环，但同一时间只跟踪最近一帧类别，未做多目标队列 / 位置跟踪；图像与对管不是一一对应时可能用旧类别触发；
- 推杆动作使用固定延时（wall clock），没有编码器 / 位置反馈，传送带速度变化会影响分拣落点；
- 对管触发没有去抖与边沿检测，依赖设备只在状态变化时上报；持续上报同一状态会重复推杆；
- 单张 base64 图片推理，未接入实时视频流 / 批量推理，也未导出 TorchScript / ONNX；批量场景需自行复用 `ResNetPredictor` 实例。

---

## 14. 参考

- paho-mqtt 官方文档：<https://eclipse.dev/paho/files/paho.mqtt.python/html/index.html>
- MQTT 5.0 规范：<https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html>
- WebSocket（RFC 6455）：<https://datatracker.ietf.org/doc/html/rfc6455>
- ResNet 论文（Deep Residual Learning for Image Recognition）：<https://arxiv.org/abs/1512.03385>
- PyTorch ResNet 实现：<https://github.com/pytorch/vision/blob/main/torchvision/models/resnet.py>
- PyTorch 官方预训练权重：<https://download.pytorch.org/models/resnet18-f37072fd.pth>


