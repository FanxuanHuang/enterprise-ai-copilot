# Enterprise AI Copilot

Enterprise AI Copilot 是一个分阶段构建的企业级 AI 助手求职作品集项目。

当前 V3 在 V2 LangGraph Workflow 中加入了本地 Enterprise RAG：

```text
React + TypeScript
  -> HTTP API
  -> FastAPI / Python
  -> LangGraph Workflow
  -> Local Enterprise Knowledge Retrieval
  -> DeepSeek OpenAI-compatible API（各 Node 复用同一个 LLM Service）
  -> FastAPI
  -> React 展示回答
```

V3 专注于 Document、Chunking、Embedding、Vector Store、Retrieval、Grounding 和来源追踪。保留 V2 的 Conditional Edge 与有限 revision loop；暂不包含 Tool Calling、MCP、Memory、Hybrid Search、Reranker、PostgreSQL、Docker、用户登录或 Multi-Agent。

## 当前 V3 架构

- `frontend/`: React + TypeScript + Vite 聊天界面
- `backend/`: FastAPI 后端服务
- `backend/app/api/`: API 路由
- `backend/app/core/`: 配置读取
- `backend/app/schemas/`: 请求和响应模型
- `backend/app/services/`: LLM 调用逻辑
- `backend/app/agents/`: Agent State、Nodes 和 LangGraph Workflow
- `backend/knowledge_base/`: 虚构企业政策 Markdown 文档
- `backend/data/knowledge_index.json`: 本地生成的持久化向量索引（不提交 Git）

## Workflow

```text
START
  -> Analyze
  -> Plan
  -> Knowledge Retrieval
  -> Execute
  -> Review
       | passed == true
       v
     Finalize -> END

Review
  | passed == false and revision_count < MAX_REVISION_COUNT
  v
Execute -> Review

Review
  | revision_count >= MAX_REVISION_COUNT
  v
Finalize -> END
```

默认 `MAX_REVISION_COUNT=2`，因此最多执行一次初稿和两次修订。达到上限后会用当前最佳 draft 完成 Finalize，避免无限循环。

Knowledge Retrieval 只查询预先建立的索引。Review 失败时仍直接回到 Execute，复用同一批检索结果，不重新生成文档 Embedding。

### AgentState

- `user_input`: 原始用户请求
- `analysis`: 目标、期望输出和约束
- `plan`: 带序号、动作和预期结果的执行步骤
- `needs_retrieval`: 是否需要企业内部知识
- `retrieval_query`: 面向知识库的独立检索查询
- `retrieved_chunks`: Top K 结果，包含正文、source、section 和 score
- `knowledge_context`: 传给 Execute 的格式化企业知识
- `knowledge_sufficient`: 最高相关度是否达到可信阈值
- `sources`: 最终答案展示的去重文档来源
- `draft`: Execute 生成或修订的草稿
- `review_result`: Review 的总结、问题和改进指令
- `review_passed`: Conditional Edge 使用的布尔判断
- `revision_count`: 已执行的修订次数，不包含初稿
- `final_answer`: Finalize 返回给 API 的最终答案

Analyze、Plan 和 Review 使用 DeepSeek JSON mode，并通过 Pydantic Model 验证结构；Conditional Edge 直接读取布尔值，不依赖字符串关键词。

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
  -> grounded context for Execute
  -> DeepSeek answer
  -> Sources
```

默认 `KNOWLEDGE_TOP_K=3`，`KNOWLEDGE_MIN_SCORE=0.5`。Top K 控制候选数量；只有达到阈值的候选会进入 Execute context 和最终 Sources。如果没有候选达到阈值，Execute 不调用生成模型补写政策，而是返回知识库依据不足。

### Retrieval 与 Generation

- Retrieval 负责“找事实”：从已有企业文档中返回相关原文和 metadata。
- Generation 负责“组织回答”：根据用户问题、计划和检索 context 生成自然语言。
- Analyze 对企业制度、流程、员工手册和内部 FAQ 等公司专有事实设置 `needs_retrieval=true`；一般写作、推理或公共知识问题不检索。
- Execute 的 prompt 明确规定企业内部事实只能来自 `knowledge_context`，不得用模型通用知识补全。

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

响应示例：

```json
{
  "answer": "你好，有什么可以帮助你的？"
}
```

请求和响应格式与 V1 保持一致，但后端现在会运行完整 V3 Workflow。检索成功时，`answer` 文本末尾会包含简单的 `Sources` 列表。

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
│   │   │   └── config.py
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   └── chat.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── knowledge_service.py
│   │   │   └── llm_service.py
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
│   │   └── knowledge_index.json  # generated, gitignored
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_api.py
│   │   ├── test_knowledge_service.py
│   │   ├── test_rag_workflow.py
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
