# CUA-Lark：飞书桌面端 Computer Use Agent

基于 UI 自动化 + 视觉大模型的飞书桌面操控智能体，用自然语言指令驱动飞书完成日常操作。

## 功能演示

| 意图 | 示例指令 | 执行路径 |
|------|---------|---------|
| 发送消息 | `给张三发消息说明天开会取消了` | 搜索联系人 → 点击 → 输入 → 发送 |
| 创建日程 | `明天下午3点到4点开个需求评审的会` | 进入日历 → 填写标题时间 → 保存 |
| 创建待办文档 | `创建一个今日任务的待办文档，内容是健身、写代码、做饭` | 新建云文档 → 填写标题 → 插入待办事项块 |

所有场景完成后自动**视觉验证**（截图 + VLM 问答），失败时最多重试 2 次。

## 快速开始

### 1. 环境准备

```bash
pip install -r requirements.txt
```

### 2. 配置 .env

在项目根目录创建 `.env` 文件：

```env
# 火山引擎 Ark 平台 API Key
ARK_API_KEY=your_ark_api_key

# 视觉模型接入点（用于 UI 操作预测和结果验证）
VISION_EP=doubao-seed-1-6-vision-250528

# 规划/对话模型接入点（用于意图识别和槽位提取）
PLANNER_EP=doubao-seed-2-0-lite-250528
```

> UI-TARS 权限开放后，将 `UI_TARS_MODEL` 设为对应接入点即可，代码无需修改。

### 3. 启动

```bash
# 确保飞书桌面端已打开并停在主界面
python -m cua_lark.main
```

## 系统架构

```
用户自然语言输入
      ↓
┌─────────────────────┐
│   对话层（LLM）      │  意图识别 + 槽位提取 + 多轮追问
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│   规划层（模板库）   │  槽位 → 步骤序列（TaskTemplate）
└──────────┬──────────┘
           ↓
┌─────────────────────────────────────────┐
│            执行层（AgentLoop）           │
│  tree 路由：pywinauto UI 树 → 精确坐标  │
│  keyboard：pyautogui 键盘/鼠标          │
│  vision 路由：截图 → VLM → 坐标         │
└──────────┬──────────────────────────────┘
           ↓
┌─────────────────────┐
│   验证层（VLM）      │  截图 + YES/NO 问答 → 自动重试
└─────────────────────┘
```

### 混合路由策略

飞书基于 Electron 构建，页面内容在 Chromium 渲染区，UI 树不可见。本项目采用三种路由组合：

- **tree**：导航按钮、对话框控件等 Native 区域 → 通过 pywinauto UIA 获取精确坐标，**不依赖视觉模型**
- **keyboard**：文本输入、快捷键 → pyautogui，支持中文（剪贴板粘贴）
- **vision**：空输入框、搜索结果列表等 Chromium 区域 → 截图交给视觉模型识别坐标

## 项目结构

```
cua_lark/
├── main.py                    # 对话入口（REPL 循环）
├── config.py                  # 配置读取（.env）
├── core/
│   ├── api_client.py          # 视觉模型封装（predict + verify）
│   └── logger.py              # 统一日志
├── perception/
│   └── tree_parser.py         # UI 树解析（pywinauto UIA）
├── execution/
│   ├── cua_executor.py        # 鼠标键盘封装
│   └── agent_loop.py          # 步骤执行主循环 + 验证重试
├── planning/
│   └── template_library.py    # 任务模板：send_message / create_event / add_todo
├── dialogue/
│   ├── dialogue_manager.py    # 多轮对话 + 意图槽位提取
│   └── intent_router.py       # 意图 → 模板函数注册表
└── verification/
    └── verifier.py            # VerifyResult / TaskTemplate / 截图工具
```

## 后续优化方向

### UI 树地图 + 结构化 ReAct

当前方案为每个意图手写固定步骤模板，扩展新任务需要新增代码。后续计划：

1. **建立飞书 UI 静态地图**：离线遍历飞书各功能区（日历、消息、云文档等），将 UI 树元素存成结构化 JSON，给 LLM 作为"可操作控件目录"使用。

2. **ReAct 执行循环**：每步规划时，将当前实时 UI 树（控件名 + 坐标）和截图同时提供给 LLM，LLM 输出：
   - `tree_click "Button '创建日程'"` → 直接查坐标，精确执行
   - `vision_click` → 截图给视觉模型，处理 Chromium 区域
   - `type / key` → 键盘输入

3. **效果**：无需手写模板，用自然语言描述任意飞书任务即可执行，兼顾 UI 树的确定性和视觉模型的灵活性。

## 依赖

- Python 3.11+，Windows 10/11
- 火山引擎 Ark 平台：Doubao-Seed 视觉模型 + 文字模型
- pywinauto、pyautogui、pywin32
