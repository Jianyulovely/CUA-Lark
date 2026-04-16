# CUA-Lark 项目设计文档 v3：混合驱动架构与模块化实现

---

## 1. 项目愿景

构建一个具备高响应速度、强鲁棒性的飞书自动化操作 Agent，通过"结构化数据优先、视觉感知补位"的策略，实现对飞书桌面端全场景的功能覆盖与自动验证。

系统支持自然语言多轮对话补全任务意图，并在执行层提供自动重试与错误恢复机制，真正做到像人一样理解指令、操作界面、验证结果。

---

## 2. 核心架构逻辑

项目采用**四层架构**：对话层 → 规划层 → 感知层 → 执行层。

```
用户自然语言输入
        │
        ▼
┌───────────────────────────────────┐
│           对话层 (Dialogue)        │
│  意图识别 → 槽位提取 → 补全追问     │
│  最多追问 2 轮，仍缺失则报错退出    │
└───────────────┬───────────────────┘
                │ 完整的意图 + 槽位
                ▼
┌───────────────────────────────────┐
│           规划层 (Planning)        │
│  命中模板 → 直接取步骤序列（快速）  │
│  未命中   → LLM 自主规划（灵活）   │
└───────────────┬───────────────────┘
                │ 结构化步骤列表
                ▼
┌───────────────────────────────────┐
│       感知 + 执行循环 (Agent Loop) │
│                                   │
│  ┌─────────────────────────────┐  │
│  │  截图 (Screenshot)          │  │
│  │       ↓                     │  │
│  │  Hybrid Router              │  │
│  │  (UI树 / 视觉 二选一)        │  │
│  │       ↓                     │  │
│  │  UI-TARS 预测动作            │  │
│  │       ↓                     │  │
│  │  执行 (click/type/key)      │  │
│  │       ↓                     │  │
│  │  验证结果                    │  │
│  │  成功 → 下一步               │  │
│  │  失败 → 重试(最多2次) → 退出 │  │
│  └─────────────────────────────┘  │
└───────────────────────────────────┘
```

---

## 3. 项目代码结构

```
cua_lark/
├── main.py                    # 启动入口：驱动对话循环与 Agent 主循环
├── config.py                  # 全局配置：API 密钥、模型接入点、重试次数上限等
│
├── core/                      # 核心基础能力
│   ├── test_state_manager.py  # 测试状态管理（见 4.3）
│   └── api_client.py          # UI-TARS (火山引擎) API 封装，支持流式响应解析
│
├── dialogue/                  # 对话层：理解用户说的是什么
│   ├── dialogue_manager.py    # 多轮对话驱动：管理 DialogueState，控制追问逻辑
│   └── intent_router.py       # 意图路由：关键词匹配模板 / 降级到自主规划
│
├── planning/                  # 规划层：决定要执行哪些步骤
│   ├── template_library.py    # 模板库：预定义飞书场景的步骤序列（见 4.5）
│   ├── task_planner.py        # 自主规划：调用 LLM 拆解模板未覆盖的任务
│   └── action_chunker.py      # 动作打包：将单步决策合并为原子序列
│
├── perception/                # 感知层：看懂当前界面在哪、是什么
│   ├── tree_parser.py         # 结构化数据：pywinauto 提取 UI 树坐标；支持 scroll_and_scan() 处理可滚动区域
│   ├── vision_agent.py        # 视觉感知：截图 + UI-TARS 预测下一动作
│   └── hybrid_router.py       # 智能路由：优先 UI 树，复杂场景降级到视觉
│
├── execution/                 # 执行层：真正操作鼠标和键盘
│   ├── agent_loop.py          # Agent 主循环：observe→decide→act→verify（见 4.6）
│   ├── cua_executor.py        # 执行器：将逻辑动作映射为 HID 指令
│   └── coord_mapper.py        # 坐标校准：处理 DPI 缩放与分辨率对齐
│
└── verification/              # 验证层：确认操作是否真的成功了
    ├── state_verifier.py      # 状态检查：通过 UI 树节点变化确认操作生效
    └── visual_checker.py      # 视觉闭环：关键帧截图比对验证业务结果
```

---

## 4. 关键模块功能详解

### 4.1 Hybrid Router（感知路由）

> **实测背景：** 飞书桌面端基于 Electron（Chromium）构建，主内容区为 Web 渲染层。经 pywinauto 实测，UI 树暴露了导航栏、搜索框区域及输入框占位文本，但不暴露 `Edit` 控件本身，且所有元素 `auto_id` 均为空。坐标为实时屏幕绝对坐标，每次执行前必须重新查询。部分弹窗（如"创建日程"）以独立顶层窗口形式打开，需单独连接扫描。含 `Group name='scrollable content'` 的区域存在滚动内容，初始扫描只能获取视口内元素，访问折叠区域需先滚动再重扫。

**三种路由策略：**

| 策略 | 适用场景 | 执行方式 |
|------|----------|----------|
| `tree` | 导航标签、筛选按钮、输入框定位 | `tree_parser` 实时查询坐标后点击 |
| `vision` | 动态内容（搜索结果列表、联系人头像） | 截图 + UI-TARS 预测坐标 |
| `keyboard` | 打开搜索、发送消息、确认操作 | 直接发送快捷键，无需定位 |

**核心技巧——占位文本定位法：**

飞书输入框虽不暴露 `Edit` 控件，但输入框内的占位文本（placeholder）会作为 `Text` 节点出现在 UI 树中。通过查找占位文本的坐标即可精准点击激活输入框：

```python
# 搜索输入框：通过占位文本定位
{"control_type": "Text", "name": "问你想问的问题，或搜索关键词"}

# 消息输入框：通过占位文本定位（name 包含"发送给"）
{"control_type": "Text", "name_contains": "发送给"}
```

**`target_selector` 数据结构（`auto_id` 均为空，只用 `name` 匹配）：**

```python
@dataclass
class UITreeSelector:
    control_type: str                 # 如 "TabItem", "Button", "Text"
    name: str | None = None           # 精确匹配
    name_contains: str | None = None  # 模糊匹配（用于动态占位文本）
```

**实测可用的关键元素（坐标实时查询，此处仅列控件特征）：**

| 元素 | control_type | name 特征 | 备注 |
|------|-------------|-----------|------|
| 搜索按钮 | `Button` | `搜索（Ctrl＋K）` | 可用快捷键替代 |
| 消息导航 | `TabItem` | `消息` | 左侧导航栏 |
| 日历导航 | `TabItem` | `日历` | 左侧导航栏 |
| 搜索输入框 | `Text` | `问你想问的问题，或搜索关键词` | 占位文本定位 |
| 联系人筛选 | `Button` | `联系人` | 搜索弹窗内 |
| 消息输入框 | `Text` | `发送给 {群/人名}` | 占位文本定位 |

---

### 4.2 Action Chunker（动作打包）

为减少 UI-TARS 的 API 往返次数，该模块将多个原子动作合并为一个"动作块"。

**分块策略：** 以 `vision` 步骤为天然分割点——`vision` 步骤前必须截图，因此它之前的连续 `tree`/`keyboard` 步骤可以打包成一个 chunk 一起执行，中间无需截图。

```
Step 1 [keyboard] ─┐
Step 2 [tree]      ├─ Chunk A（打包执行，不调用 UI-TARS）
Step 3 [keyboard]  ┘

Step 4 [vision]    ──  截图 → UI-TARS 预测 → 执行（单独一步）

Step 5 [tree]      ─┐
Step 6 [keyboard]  ┘─ Chunk B（打包执行，不调用 UI-TARS）
```

**数据结构：**

```python
@dataclass
class AtomicAction:
    type: Literal["click", "type", "key", "wait"]
    x: int | None = None          # click 时使用
    y: int | None = None          # click 时使用
    text: str | None = None       # type 时使用
    key_combo: str | None = None  # key 时使用，如 "ctrl+k", "enter"
    ms: int | None = None         # wait 时使用

@dataclass
class ActionChunk:
    step_ids: list[str]           # 本 chunk 包含的步骤编号
    routing: Literal["tree_keyboard", "vision"]
    sequence: list[AtomicAction]
    screenshot_after: bool        # 执行后是否截图（用于验证）
```

**示例：** `send_message` 的搜索阶段打包为一个 chunk：
```python
ActionChunk(
    routing="tree_keyboard",
    sequence=[
        AtomicAction(type="key", key_combo="ctrl+k"),
        AtomicAction(type="wait", ms=500),
        AtomicAction(type="click", x=679, y=187),   # 搜索输入框（实时查询）
        AtomicAction(type="type", text="张三"),
        AtomicAction(type="wait", ms=800),           # 等搜索结果加载
    ],
    screenshot_after=True   # 之后需要截图让 UI-TARS 找联系人
)
```

---

### 4.3 Test State Manager（测试状态管理）

> **设计决策：** 本项目不引入虚拟机沙箱，改用"软隔离"策略——通过代码在测试前后管理飞书的状态，等效实现环境隔离。

**执行前（Pre-check）：**
- 确认飞书桌面端处于主界面
- 检查网络连接与账号登录状态
- 记录测试开始前的界面快照（用于对比）

**执行后（Teardown）：**
- 撤回/删除本次测试发送的消息
- 删除本次测试创建的日程、文档
- 将飞书界面恢复到主界面

---

### 4.4 Dialogue Manager（多轮对话管理）

**核心数据结构：**

```python
@dataclass
class DialogueState:
    intent: str           # 识别到的意图名，如 "send_message"
    filled_slots: dict    # 已收集的槽位，如 {"recipient": "张三"}
    missing_slots: list   # 仍缺失的必填槽位，如 ["content"]
    turn_count: int       # 已追问次数，最大值为 2
```

**处理流程：**
1. 调用 LLM 从用户输入中提取槽位，合并进 `filled_slots`
2. 检查 `missing_slots` 是否为空
   - **为空** → 槽位完整，交给规划层
   - **不为空，`turn_count` < 2** → 生成追问，等待用户补充
   - **不为空，`turn_count` >= 2** → 报错退出，提示用户重新描述任务

**槽位提取方式：** LLM 在做意图识别的同一次调用中同步完成槽位提取，一次 API 返回"意图 + 槽位 + 缺失项"三合一结果，避免额外延迟。

---

### 4.5 Template Library（任务模板库）

预定义的步骤序列，覆盖最高频的飞书操作场景。命中模板时，规划层直接取出步骤，无需 LLM 规划调用。

---

#### 模板一：搜索联系人并发送文字消息（`send_message`）

| 属性 | 内容 |
|------|------|
| 意图名 | `send_message` |
| 触发词 | 发消息 / 发送 / 告诉 / 通知 / 给…说 |

**槽位定义：**

| 槽位 | 是否必填 | 说明 |
|------|----------|------|
| `recipient` | 必填 | 联系人姓名 |
| `content` | 必填 | 消息正文 |

**执行步骤（基于实测 UI 树修正）：**

```
Step 1: 按 Ctrl+K 打开搜索           [keyboard] ─┐ Chunk A
Step 2: 点击搜索输入框                [tree]      │ 占位文本定位
Step 3: 输入 {recipient}              [keyboard]  │ type
Step 4: 点击"联系人"筛选按钮           [tree]     ─┘ Button name='联系人'
        ↑ 以上4步无需截图，打包执行
Step 5: 从搜索结果中点击 {recipient}  [vision]    单独截图 → UI-TARS
        ↑ 动态列表，必须靠视觉识别
Step 6: 点击消息输入框                [tree]     ─┐ Chunk B
Step 7: 输入 {content}                [keyboard]  │ 占位文本定位
Step 8: 按 Enter 发送                 [keyboard] ─┘
```

**验证：** 消息输入框占位文本消失，且对话区域出现包含 `{content}` 的 `Text` 节点（UI 树可读）

---

#### 模板二：创建日程（`create_event`）

| 属性 | 内容 |
|------|------|
| 意图名 | `create_event` |
| 触发词 | 创建日程 / 新建日程 / 安排会议 / 约…开会 |

**槽位定义：**

| 槽位 | 是否必填 | 说明 |
|------|----------|------|
| `title` | 必填 | 日程标题 |
| `date` | 必填 | 日期（支持"明天"、"下周一"等自然语言，由 LLM 解析为具体日期） |
| `start_time` | 必填 | 开始时间（支持"下午三点"等表达） |
| `end_time` | 选填 | 结束时间（未提供时默认为 start_time + 1 小时） |

**执行步骤（基于实测 UI 树修正）：**

> **重要发现：** "创建日程"弹窗以**独立顶层窗口**（`title='创建日程'`）形式打开，
> 需要在代码中主动连接到新窗口。弹窗内暴露了绝大多数控件。

```
Step 1: 点击"日历"导航标签              [tree - 主窗口]   TabItem name='日历'    ─┐ Chunk A
Step 2: 点击"创建日程"按钮              [tree - 主窗口]   Button name='创建日程' ─┘
        → 等待并连接到新窗口 title='创建日程'

Step 3: 点击标题输入框，输入 {title}     [vision]  标题框为空，UI 树不可见，唯一需要 UI-TARS 的步骤

Step 4: 点击开始时间，设置 {start_time} [tree - 对话框]   Text 显示当前时间，点击后出现时间选择器
Step 5: 点击结束时间，设置 {end_time}   [tree - 对话框]   Text 显示当前结束时间
Step 6: 点击"保存"按钮                  [tree - 对话框]   Button name='保存'
```

**对话框内可用的 tree 控件（实测）：**

| 控件 | 类型 | 定位方式 |
|------|------|----------|
| 开始日期/时间 | `Text` | 对话框内 y≈400 处，显示当前日期时间 |
| 结束时间 | `Text` | 对话框内 y≈400 处，紧跟开始时间 |
| 全天 | `CheckBox` | `name='全天'` |
| 添加联系人 | `Text` | 占位文本 `name='添加联系人、群或邮箱'` |
| 保存 | `Button` | `name='保存'` |
| 取消 | `Button` | `name='取消'` |

> 与 `send_message`（1 次 UI-TARS）相比，`create_event` 同样只需 **1 次** UI-TARS 调用（定位空白标题框）。
> 弹窗是独立窗口这一架构特性，使得表单控件对 pywinauto 完全可见。

**验证：** 弹窗关闭后，日历主视图中出现新日程；或通过 UI 树读取 `Document name='calendar'` 下的新增文本节点确认。

---

### 4.6 Agent Loop（执行主循环）

每个步骤的执行遵循"执行-验证-重试"闭环，最大限度保证鲁棒性。

**伪代码：**

```python
MAX_RETRY = 2

for step in task_steps:
    for attempt in range(MAX_RETRY + 1):      # 最多执行 3 次
        screenshot = capture_screen()
        action = ui_tars.predict(
            image=screenshot,
            instruction=step.instruction
        )
        cua_executor.execute(action)

        if verifier.check(step.expected_state):
            break                              # 验证通过，进入下一步
        
        if attempt == MAX_RETRY:
            raise StepFailedError(step)        # 重试耗尽，报错退出
        
        time.sleep(0.5)                        # 短暂等待后重试
```

**重试策略说明：**
- 每次重试都**重新截图**，确保 UI-TARS 看到的是最新界面状态
- 等待 0.5 秒是为了给飞书界面留出动画/渲染时间
- 报错退出时向用户返回具体失败步骤，方便排查

---

## 5. 开发流程建议

**阶段一：感知基准线**
运行 `tree_parser` 打印当前飞书主界面的全部可点击节点，验证 pywinauto 能正常读取飞书的 UI 树。

**阶段二：执行闭环（单步）**
手动指定坐标，跑通 `cua_executor` 的点击和输入，调试 `coord_mapper` 的 DPI 校准。

**阶段三：单模板跑通**
实现 `send_message` 模板的完整链路：槽位 → 步骤 → 执行 → 验证。

**阶段四：接入 UI-TARS**
将 Step 3（点击联系人）替换为 UI-TARS 视觉预测，对比精度与直接坐标的差异。

**阶段五：扩展第二个模板**
在 `send_message` 稳定后，扩展 `create_event`，重点调试日期导航逻辑。

**阶段六：对话层接入**
接入 `dialogue_manager`，实现不完整指令的自动追问能力。
