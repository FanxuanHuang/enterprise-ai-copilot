# Enterprise AI Copilot

Enterprise AI Copilot 是一个分阶段构建的企业级 AI 助手求职作品集项目。

当前 V4 在 V3 Enterprise RAG 基础上加入了原生 Tool Calling、Agent Loop、SQLite 持久化、基础会话、权限检查和可观测性：

```text
React + TypeScript
  -> HTTP API
  -> FastAPI / Python
  -> LangGraph Workflow
  -> Local Enterprise Knowledge Retrieval
  -> DeepSeek OpenAI-compatible Tool Calling
  -> Python Tool Dispatcher
  -> Service / Repository / SQLite
  -> FastAPI
  -> React 展示回答
```

V4 保留 V1 API、V2 revision loop 和 V3 RAG，并让模型判断何时需要企业工具。模型只生成 Tool Call，真正的权限检查、参数校验、数据库查询和写入全部由 Python 完成。当前仍不包含 MCP、复杂长期 Memory、完整认证/RBAC、PostgreSQL、Docker、微服务或 Multi-Agent。

## 异步调用链

FastAPI 聊天路由、LangGraph LLM 节点、Workflow 调用和 DeepSeek OpenAI-compatible 请求使用原生 `async/await`：

```text
async POST /api/chat
  -> await run_workflow
  -> await workflow.ainvoke
  -> async Analyze / Plan / Agent Decide / Review / Finalize
  -> AsyncOpenAI
  -> await chat.completions.create
```

现有 SQLite、Repository、Tool Dispatcher 和本地 Embedding 仍是同步实现。为避免它们阻塞 FastAPI event loop，数据库初始化、会话持久化、知识检索和 Tool 执行通过 `asyncio.to_thread` 运行。共享 FastEmbed 模型的查询使用锁串行执行，避免未知的跨线程模型安全问题，但不会占用 event loop。轻量的 LangGraph 路由、状态转换、JSON/Pydantic 数据组装保持同步。

## 当前 V4 架构

- `frontend/`: React + TypeScript + Vite 聊天界面
- `backend/`: FastAPI 后端服务
- `backend/app/api/`: API 路由
- `backend/app/core/`: 配置和请求可观测性
- `backend/app/schemas/`: 请求和响应模型
- `backend/app/services/`: LLM、企业业务和会话服务
- `backend/app/agents/`: Agent State、Nodes 和 LangGraph Workflow
- `backend/app/tools/`: Tool Schema、Python Handler 和 Dispatcher/Registry
- `backend/app/repositories/`: SQLite 数据访问层
- `backend/app/db/`: 数据库连接、表结构和 demo data 初始化
- `backend/knowledge_base/`: 虚构企业政策 Markdown 文档
- `backend/data/knowledge_index.json`: 本地生成的持久化向量索引（不提交 Git）
- `backend/data/enterprise_ai_copilot.db`: 自动生成的 SQLite 数据库（不提交 Git）

## Workflow

```text
START
  -> Analyze
  -> Plan
  -> Knowledge Retrieval
  -> Agent Decide
       | tool_calls
       v
     Tool Execution
       |
       +----> Agent Decide
       |
       | draft
       v
  -> Review
       | passed == true
       v
     Finalize -> END

Review
  | passed == false and revision_count < MAX_REVISION_COUNT
  v
Prepare Revision -> Agent Decide

Review
  | revision_count >= MAX_REVISION_COUNT
  v
Finalize -> END
```

默认 `MAX_REVISION_COUNT=2`，因此最多执行一次初稿和两次修订。达到上限后会用当前最佳 draft 完成 Finalize，避免无限循环。

默认 `MAX_TOOL_ITERATIONS=4`。每次 `Agent Decide -> Tool Execution -> Agent Decide` 计为一轮；达到上限后禁止执行新 Tool，并根据已有 observation 安全结束。`revision_count` 与 `tool_iteration_count` 完全独立。

Knowledge Retrieval 只查询预先建立的索引。Review 失败时复用同一批 RAG 结果和已有 Tool observation，不重新生成文档 Embedding，也不默认重复已成功的写操作。

### AgentState

- `user_input`: 原始用户请求
- `analysis`: 目标、期望输出和约束
- `plan`: 带序号、动作和预期结果的执行步骤
- `needs_retrieval`: 是否需要企业内部知识
- `retrieval_query`: 面向知识库的独立检索查询
- `retrieved_chunks`: Top K 结果，包含正文、source、section 和 score
- `knowledge_context`: 传给 Agent Decide 的格式化企业知识
- `knowledge_sufficient`: 最高相关度是否达到可信阈值
- `sources`: 最终答案展示的去重文档来源
- `request_id`、`session_id`、`user_context`: 请求和调用者上下文
- `conversation_history`: 同一 session 的近期聊天记录
- `agent_messages`: 发送给 Tool Calling API 的合法消息序列
- `current_tool_calls`: 本轮待执行调用
- `tool_calls`、`tool_results`: 可审计的调用和 observation
- `agent_steps`: 不包含隐藏推理的执行轨迹摘要
- `tool_iteration_count`、`tool_limit_reached`: Tool Loop Guardrail
- `draft`: Agent Decide 生成或修订的草稿
- `review_result`: Review 的总结、问题和改进指令
- `review_passed`: Conditional Edge 使用的布尔判断
- `revision_count`: 已执行的修订次数，不包含初稿
- `final_answer`: Finalize 返回给 API 的最终答案

Analyze、Plan 和 Review 使用 DeepSeek JSON mode，并通过 Pydantic Model 验证结构；Conditional Edge 直接读取布尔值，不依赖字符串关键词。

## Tool Calling

V4 提供三个工具：

- `get_employee_info(employee_id)`：查询员工部门、职级和角色。
- `get_application_status(application_id)`：查询企业申请状态。
- `create_business_trip_application(employee_id, destination, days, reason?)`：创建并持久化出差申请。

`ToolRegistry` 为 DeepSeek 提供 OpenAI-compatible JSON Schema。Dispatcher 按 tool name 查找定义、解析 JSON、通过 Pydantic 校验参数、调用 Python handler，并将统一的 `ToolResult` 作为 `role=tool` 消息返回模型。未知工具、参数错误、not-found、无权限和数据库异常都会返回结构化错误，不会让单个 Tool 直接击穿 Agent Loop。

同一轮工作流内，如果模型重复提交参数完全相同且此前已经成功的 Tool Call，执行节点会复用原结果，避免重复写入。Review 和 Finalize 同时接收 Tool Results；最终答案必须删除数据库结果中不存在的日期、费用、状态、编号等业务字段。

## SQLite 与权限

应用启动或首次调用时会幂等创建：

- `employees`：员工、部门、职级和演示角色。
- `applications`：出差申请和状态。
- `conversations`：基础 session 元数据。
- `messages`：user/assistant 聊天记录。

预置 `E1001 / 研发 / P6`、manager/admin 演示账号以及 `TRIP-2026-001 / 审批中`。employee 只能访问自己及自己的申请；manager/admin 可以访问其他员工。权限在 Python Service 层执行，不能由 LLM 绕过。

`user_id` 只是 V4 本地演示身份，不是登录认证。生产环境必须由可信认证中间件注入用户身份，不能信任客户端自行提交的 `user_id`。

## RAG 与 Tool 的边界

- RAG 获取政策、手册和制度等相对静态的内部知识。
- Tool 获取实时业务数据或执行有副作用的企业操作。
- “远程办公政策是什么”只走 RAG。
- “申请 TRIP-2026-001 的状态”走 Tool。
- “根据差旅政策创建申请”先 RAG，再由 Agent 调用 Tool。

## RAG 技术方案

### Embedding

使用 FastEmbed 和中文模型 `BAAI/bge-small-zh-v1.5`：

- 本地 ONNX 推理，不需要额外云服务或 Embedding API Key。
- 512 维中文语义向量，适合当前中文企业政策 demo。
- Indexing 使用 `passage_embed`，Query 使用 `query_embed`，两个阶段职责明确。
- 相比 Sentence Transformers，不需要完整 PyTorch 运行时。

项目为当前 macOS 13.1 开发环境固定了 `onnxruntime==1.19.2`。更新该版本前，应检查 wheel 的最低 macOS 版本。

### Vector Store

`KnowledgeService` 把 chunk metadata 和 embedding 持久化到一个 JSON 索引，并在查询时执行 cosine similarity 排序。当前只有少量 demo 文档，线性搜索足够快，也更便于直接观察向量、分数和 metadata。生产级大规模知识库再考虑独立 Vector DB。

### Chunking

- 先按 Markdown heading 拆 section。
- 超长 section 再按 600 字符拆分。
- 相邻 chunk 默认保留 100 字符 overlap，减少边界信息丢失。
- 每个 chunk 保留 `source`、`section` 和文档内 `chunk_index`。

## Indexing 与 Query Pipeline

### A. Indexing Pipeline

```text
knowledge_base/*.md
  -> Markdown Document Loader
  -> heading-aware chunking (600 / overlap 100)
  -> BGE passage embeddings
  -> backend/data/knowledge_index.json
```

安装依赖后，提前建立索引：

```bash
cd backend
.venv/bin/python -m app.scripts.build_knowledge_index
```

首次运行会下载约 90 MB 的本地 Embedding 模型。修改知识文档、Embedding 模型或 chunk 参数后，应重新执行此命令。应用不会在每次 `/api/chat` 请求中重新加载文档或重新计算文档向量。

### B. Query Pipeline

```text
user question
  -> Analyze decides whether enterprise retrieval is needed
  -> standalone retrieval_query
  -> BGE query embedding
  -> cosine similarity
  -> Top K chunks
  -> relevance threshold
  -> grounded context for Agent Decide
  -> DeepSeek answer
  -> Sources
```

默认 `KNOWLEDGE_TOP_K=3`，`KNOWLEDGE_MIN_SCORE=0.5`。Top K 控制候选数量；只有达到阈值的候选会进入 Agent Decide context 和最终 Sources。如果没有候选达到阈值，Agent 不调用生成模型补写政策，而是返回知识库依据不足。

### Retrieval 与 Generation

- Retrieval 负责“找事实”：从已有企业文档中返回相关原文和 metadata。
- Generation 负责“组织回答”：根据用户问题、计划和检索 context 生成自然语言。
- Analyze 对企业制度、流程、员工手册和内部 FAQ 等公司专有事实设置 `needs_retrieval=true`；一般写作、推理或公共知识问题不检索。
- Agent Decide 的 prompt 明确规定企业内部事实只能来自 `knowledge_context`，不得用模型通用知识补全。

## 前端启动方法

进入前端目录：

```bash
cd frontend
```

安装依赖：

```bash
npm install
```

启动开发服务器：

```bash
npm run dev
```

默认访问：

```text
http://localhost:5173
```

## 后端创建 Python 3.12 虚拟环境

进入后端目录：

```bash
cd backend
```

创建虚拟环境：

```bash
python3.12 -m venv .venv
```

激活虚拟环境：

```bash
source .venv/bin/activate
```

## 安装后端依赖

```bash
pip install -r requirements.txt
```

## .env 配置方法

复制示例环境变量文件：

```bash
cp .env.example .env
```

在 `backend/.env` 中填写：

```text
DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

不要把真实 API Key 提交到 Git。

可选配置：

```text
MAX_REVISION_COUNT=2
MAX_TOOL_ITERATIONS=4
KNOWLEDGE_TOP_K=3
KNOWLEDGE_MIN_SCORE=0.5
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
```

## 启动后端

在 `backend/` 目录下执行：

```bash
uvicorn app.main:app --reload
```

默认后端地址：

```text
http://localhost:8000
```

健康检查：

```text
GET http://localhost:8000/health
```

聊天接口：

```text
POST http://localhost:8000/api/chat
```

请求示例：

```json
{
  "message": "你好"
}
```

V4 可选上下文：

```json
{
  "message": "查询员工 E1001 的部门和职级",
  "session_id": "browser-session-001",
  "user_id": "E1001"
}
```

响应示例：

```json
{
  "answer": "你好，有什么可以帮助你的？"
}
```

只传 `message` 的 V1 请求和 `answer` 响应保持兼容。`session_id` 和 `user_id` 均有默认行为；前端会在当前页面生命周期内复用一个 session。检索成功时，`answer` 文本末尾会包含简单的 `Sources` 列表。

## 可观测性

日志包含 request ID、workflow stage、检索查询、来源、Tool 名称、参数字段名、Tool 状态、两个循环计数和延迟。日志不记录 API Key、Secret、完整员工记录或完整任意工具载荷。HTTP 响应同时返回 `X-Request-ID`。

## 验证

后端：

```bash
cd backend
.venv/bin/python -m compileall app tests
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
.venv/bin/python -c "from app.main import app; print(app.title, app.version)"
```

前端：

```bash
cd frontend
npm run lint
npm run build
```

## 当前目录结构

```text
enterprise-ai-copilot/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── chat.py
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── nodes.py
│   │   │   ├── state.py
│   │   │   └── workflow.py
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   └── observability.py
│   │   ├── db/
│   │   │   ├── database.py
│   │   │   └── models.py
│   │   ├── repositories/
│   │   │   ├── application_repository.py
│   │   │   ├── conversation_repository.py
│   │   │   └── employee_repository.py
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   └── chat.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── conversation_service.py
│   │   │   ├── enterprise_services.py
│   │   │   ├── knowledge_service.py
│   │   │   └── llm_service.py
│   │   ├── tools/
│   │   │   ├── application_tools.py
│   │   │   ├── employee_tools.py
│   │   │   ├── registry.py
│   │   │   └── schemas.py
│   │   ├── scripts/
│   │   │   └── build_knowledge_index.py
│   │   ├── __init__.py
│   │   └── main.py
│   ├── knowledge_base/
│   │   ├── employee_handbook.md
│   │   ├── reimbursement_policy.md
│   │   ├── remote_work_policy.md
│   │   └── travel_policy.md
│   ├── data/
│   │   ├── knowledge_index.json          # generated, gitignored
│   │   └── enterprise_ai_copilot.db      # generated, gitignored
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_api.py
│   │   ├── test_database.py
│   │   ├── test_knowledge_service.py
│   │   ├── test_rag_workflow.py
│   │   ├── test_tool_workflow.py
│   │   ├── test_tools.py
│   │   └── test_workflow.py
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   └── chatApi.ts
│   │   ├── components/
│   │   │   ├── ChatInput.tsx
│   │   │   ├── MessageList.tsx
│   │   │   └── StatusMessage.tsx
│   │   ├── App.css
│   │   ├── App.tsx
│   │   ├── index.css
│   │   ├── main.tsx
│   │   └── types.ts
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── tsconfig.node.json
│   └── vite.config.ts
├── .gitignore
└── README.md
```
