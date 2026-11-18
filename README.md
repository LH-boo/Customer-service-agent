# 仁心医院 · 智能客服工单 Agent

面向医院患者服务中心的智能客服工单系统，覆盖「患者提问 → Agent 判断 → 查询业务数据 → 创建工单 → 部门流转 → 患者查看进度」的完整闭环。

技术栈：**FastAPI · LangChain · LangGraph · RAG（Milvus + Elasticsearch + RRF + Reranker）· MCP · MySQL · Redis · Docker**

> 项目定位：模拟医院真实患者服务场景，不是医疗问答机器人。系统不提供诊断、处方或治疗方案；急危重症优先提示拨打 120，不进入普通工单流程。

---

## 1. 核心能力

| 能力 | 实现 |
| --- | --- |
| 意图识别与分类 | LLM 结构化输出 + 关键词规则兜底（无 API Key 也能运行） |
| 静态知识检索 | Markdown 知识库切分、中文 BM25 / ES 关键词召回、Milvus 语义召回、RRF 融合、可选 Reranker |
| 实时业务查询 | MCP Server 暴露预约、报告、费用、科室、工单等工具 |
| 工单闭环 | 创建工单 → 分配部门 → 写入制度依据 → 患者端查看流转记录 |
| 安全控制 | JWT 身份绑定、SQL 按 `patient_id` 隔离、手机号/身份证脱敏、紧急症状拦截、取消预约二次确认 |
| 性能与稳定性 | Redis 缓存 FAQ / 会话 / 工单状态；Redis 不可用时自动降级内存缓存；工具异常降级与转人工 |
| 可观测 | 每轮回复返回 `trace`，前端可展开查看 Agent 各节点执行过程 |

## 2. 架构

```text
┌──────────────────────────── 患者端 Web ────────────────────────────┐
│  在线客服 · 工单列表 · 工单详情 · 处理进度（原生 HTML/CSS/JS）      │
└───────────────────────────────┬───────────────────────────────────┘
                                │ HTTP + JWT
┌───────────────────────────────▼───────────────────────────────────┐
│                         FastAPI 统一入口                           │
│   /api/auth/login   /api/chat   /api/tickets   /health             │
└───────────────────────────────┬───────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────┐
│                    LangGraph 工单 Agent 工作流                     │
│  START → classify → safety → route ─┬→ rag ────────────┐           │
│                                     ├→ tools(MCP) ─────┤           │
│                                     ├→ ticket ─────────┼→ review → END
│                                     └→ confirm ────────┘           │
└───────────────┬───────────────────────────────┬───────────────────┘
                │                               │
     ┌──────────▼──────────┐         ┌──────────▼──────────┐
     │  RAG 知识检索        │         │  MCP 工具层          │
     │  Milvus + BM25/ES   │         │  MCP Server (stdio) │
     │  RRF + Reranker     │         │  预约/报告/工单工具   │
     └──────────┬──────────┘         └──────────┬──────────┘
                │                               │
        data/knowledge/*.md              MySQL / SQLite
                │                               │
                └────────── Redis 缓存 + LangGraph Checkpointer ─────
```

## 3. 快速开始（本地，无外部依赖）

要求 Python 3.11+。

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env      # 可选：不配置 LLM Key 时使用离线模式
uvicorn app.main:app --reload --port 8000
```

打开 <http://localhost:8000>，使用演示账号登录：

| 患者编号 | 手机号 | 说明 |
| --- | --- | --- |
| P2026001 | 13800000001 | 有预约、报告、费用与历史工单 |
| P2026002 | 13800000002 | 另一位患者，用于验证数据隔离 |

默认使用 SQLite（`data/hospital.db`，自动建表并写入演示数据）；Redis 未启动时自动使用进程内缓存。API 文档：<http://localhost:8000/docs>。

### 接入大模型

在 `.env` 中配置任意兼容 OpenAI 协议的服务：

```env
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

未配置时：意图识别走关键词规则，RAG 回答采用检索结果模板化输出，业务查询与工单流程仍然完整可用。

### 可选：向量检索 / 关键词检索 / 重排

```env
MILVUS_URI=http://127.0.0.1:19530
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIM=1024

ES_URL=http://127.0.0.1:9200
RERANK_API_URL=https://api.siliconflow.cn/v1
RERANK_API_KEY=sk-xxx
```

配置后执行知识入库：

```bash
python -m app.rag.ingest
```

未配置 Milvus/ES 时系统使用本地 BM25 检索，不影响演示。

## 4. 关键业务流程

### 4.1 投诉建议（工单闭环）

患者：*「我昨天预约了今天上午的门诊，医院临时调整了医生时间，也没有提前通知我，白跑了一趟。」*

1. `classify`：识别为「投诉建议」，优先级 high；
2. `ticket`：调用 `get_appointment` 核实预约记录，RAG 检索《医院服务制度》中的停诊通知与投诉处理时限；
3. 调用 `create_ticket` 创建工单（`waiting_human`），`assign_ticket` 分配门诊服务中心，`add_ticket_comment` 写入制度依据；
4. `review`：返回工单编号、处理部门、答复时限，并标记转人工；
5. 患者可在「我的工单」查看状态与流转时间线。

### 4.2 取消预约（二次确认 + 业务校验）

1. 患者表达取消意图后，`tools` 只执行**查询**，返回预约详情与取消截止时间，并把待执行动作写入 `state.pending_action`；
2. 患者回复「确认取消」→ `classify` 识别确认意图 → `confirm` 节点执行 `cancel_appointment`；
3. 服务层再次校验：预约归属、状态为 `booked`、距就诊时间满足 2 小时规则；任一不满足返回原因；
4. 患者回复「不取消」或切换话题，待确认动作被清除，预约保持不变。

### 4.3 检查报告查询

`get_report_status` 仅返回报告状态、科室与更新时间，并在 Prompt 与工具描述中明确禁止预测结果或给出诊断结论。

## 5. LangGraph 设计

节点职责：

| 节点 | 职责 |
| --- | --- |
| `classify` | 识别意图、类别、优先级；处理跨轮「待确认动作」 |
| `safety` | 急危重症拦截、隐私/越权请求拦截 |
| `route` | 纯条件路由，不执行业务 |
| `rag` | 混合检索 + 带来源回答；无依据时拒答并转人工 |
| `tools` | MCP 工具调用；取消预约前只查询不执行；费用争议自动建单 |
| `ticket` | 核实业务记录 + 检索制度 → 创建/分配工单 |
| `confirm` | 仅在患者明确确认后执行有副作用的操作 |
| `review` | 结果兜底、补充就医边界声明、标记转人工 |

- State 定义见 [`app/agent/state.py`](app/agent/state.py)；
- 图编排见 [`app/agent/graph.py`](app/agent/graph.py)；
- Checkpointer 默认使用 SQLite（`data/checkpoints.sqlite`），按 `patient:{id}:session:{sid}` 隔离会话，支持多轮状态与工作流恢复。

## 6. MCP 设计

MCP Server 通过 stdio 暴露 9 个工具（见 [`app/mcp/server.py`](app/mcp/server.py)、[`app/mcp/registry.py`](app/mcp/registry.py)）：

`get_appointment` · `cancel_appointment` · `get_report_status` · `get_department_info` · `get_charge_detail` · `create_ticket` · `get_ticket_status` · `assign_ticket` · `add_ticket_comment`

两种运行模式（`.env` 中 `MCP_MODE`）：

- `local`（默认）：Agent 直接调用业务服务，启动快，适合演示；
- `client`：Agent 作为 MCP Client 拉起独立 MCP Server 进程，完整演示 MCP 调用链路，失败自动降级。

调试 MCP Server：

```bash
npx @modelcontextprotocol/inspector python -m app.mcp.server
```

## 7. 数据与缓存

数据表：`patients`、`departments`、`appointments`、`reports`、`charges`、`tickets`、`ticket_logs`、`conversations`。

Redis Key：

| Key | 用途 | TTL |
| --- | --- | --- |
| `hospital:faq:{sha256}` | 高频知识问答缓存（不含个人数据） | 7 天 |
| `hospital:chat:{patient_id}:{session_id}` | 短期会话上下文 | 2 小时 |
| `hospital:ticket:{patient_id}:{ticket_no}` | 工单详情缓存 | 60 秒 |

动态数据（预约状态、报告状态）不作为长期缓存依据；FAQ 缓存仅对公共知识类问题启用。

## 8. Docker 部署

```bash
docker compose up -d --build
```

启动 app + MySQL 8 + Redis，访问 <http://localhost:8000>。MySQL 连接串、JWT 密钥、LLM Key 均通过环境变量注入。

## 9. 安全与边界

- 演示登录为患者编号 + 手机号，生产环境应接入医院统一身份认证（OAuth2 / SSO）；
- MCP 工具以 `patient_id` 做 SQL 层数据隔离；生产环境应由 MCP Server 从令牌解析身份，而非信任调用方参数；
- 对话落库前对手机号、身份证号脱敏；报告内容与费用信息最小化返回；
- 所有涉及取消预约等写操作必须经过患者二次确认与业务规则校验；
- 系统仅提供就医指引，不提供诊断、处方；急危重症提示立即拨打 120。

## 10. 目录结构

```text
app/
├─ agent/          # LangGraph 状态、节点、图、LLM、工具网关
├─ api/            # 鉴权、对话、工单接口
├─ mcp/            # MCP Server / Client / 工具注册表
├─ rag/            # 文档加载、BM25、Milvus、ES、Reranker、混合检索、入库
├─ services/       # 业务服务层（权限校验）与 Redis 缓存
├─ static/         # 患者端 Web 界面
├─ config.py       # 环境变量配置
├─ database.py     # 异步数据库连接
├─ models.py       # SQLAlchemy 数据模型
├─ seed.py         # 演示数据
└─ main.py         # FastAPI 入口
data/knowledge/    # 医院知识库（就诊/医保/制度/科室/FAQ）
tests/             # 分类与检索测试
```

## 11. 测试

```bash
pytest -q
```
