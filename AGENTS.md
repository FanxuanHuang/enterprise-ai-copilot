# Enterprise AI Copilot 项目指南

## 项目定位

Enterprise AI Copilot 是一个用于求职作品集和分阶段学习的企业级 AI 助手项目。

当前版本为 V1，只负责跑通下面这条最基础的全栈 LLM 链路：

```text
React + TypeScript
  -> HTTP API
  -> FastAPI + Python
  -> DeepSeek OpenAI-compatible API
  -> FastAPI
  -> React 展示回答
```

项目强调结构清晰、便于学习和逐步演进，但当前阶段应避免过度抽象。

## V1 范围边界

当前只实现单轮聊天请求，不要主动加入以下后续能力：

- RAG 或向量数据库
- LangGraph
- Tool Calling
- MCP
- Memory
- PostgreSQL 或其他业务数据库
- Docker
- 用户登录和权限系统

需要扩展这些能力时，应以新的版本目标为依据，不要提前把占位架构或无用依赖放入 V1。

## 技术栈

### 前端

- React 18
- TypeScript 5
- Vite 6
- 原生 CSS
- ESLint 9

### 后端

- Python 3.12
- FastAPI
- Uvicorn
- Pydantic Settings
- python-dotenv
- OpenAI Python SDK
- DeepSeek OpenAI-compatible API

## 目录职责

```text
enterprise-ai-copilot/
├── backend/
│   ├── app/
│   │   ├── api/          # HTTP 路由和错误状态映射
│   │   ├── core/         # 环境变量及应用配置
│   │   ├── schemas/      # Pydantic 请求/响应模型
│   │   ├── services/     # DeepSeek 调用逻辑
│   │   └── main.py       # FastAPI 应用、CORS、健康检查、路由注册
│   ├── .env.example      # 可提交的环境变量模板
│   └── requirements.txt  # Python 依赖及固定版本
├── frontend/
│   ├── src/
│   │   ├── api/          # 后端 HTTP 请求封装
│   │   ├── components/   # 简单聊天界面组件
│   │   ├── App.tsx       # 页面状态和发送消息流程
│   │   ├── types.ts      # 前端共享类型
│   │   └── main.tsx      # React 入口
│   └── package.json      # 前端依赖和脚本
├── .gitignore
├── AGENTS.md
└── README.md
```

生成目录和本地环境不属于源码，包括 `frontend/node_modules/`、`frontend/dist/`、`backend/.venv/` 和 Python 缓存目录。

## 后端实现约定

- `backend/app/main.py` 只负责组装 FastAPI 应用，不把业务逻辑堆入入口文件。
- API 路由位于 `backend/app/api/`。
- 请求和响应模型位于 `backend/app/schemas/`。
- LLM 调用集中在 `backend/app/services/llm_service.py`。
- 配置集中在 `backend/app/core/config.py`，通过 `pydantic-settings` 从环境变量和 `backend/.env` 读取。
- DeepSeek 模型名称使用 `DEEPSEEK_MODEL` 配置，不能散落或写死在业务代码中。
- API Key 只能通过 `DEEPSEEK_API_KEY` 提供，严禁写入源码、README、日志或提交记录。
- 当前 LLM 系统提示词为 `You are a helpful enterprise AI copilot.`。
- DeepSeek 调用失败统一转换为 `LLMServiceError`，聊天路由将其返回为 HTTP 502。
- 当前接口是同步实现。除非有明确需求，不要仅为形式上的“企业级”引入额外分层、依赖注入框架或异步封装。

## API 契约

### 健康检查

```http
GET /health
```

成功响应：

```json
{
  "status": "ok"
}
```

### 聊天接口

```http
POST /api/chat
Content-Type: application/json
```

请求体：

```json
{
  "message": "你好"
}
```

`message` 必填，长度范围为 1 到 4000 个字符。

成功响应：

```json
{
  "answer": "你好，有什么可以帮助你的？"
}
```

## 前端实现约定

- `App.tsx` 管理消息列表、加载状态、错误状态和发送流程。
- `ChatInput` 负责输入、去除首尾空白、防止空消息提交，并在请求期间禁用输入。
- `MessageList` 负责展示用户消息、助手消息和加载提示。
- `StatusMessage` 负责基础错误提示。
- API 调用统一放在 `src/api/chatApi.ts`，不要在组件内重复拼接请求。
- 后端地址优先读取 `VITE_API_BASE_URL`，未配置时使用 `http://localhost:8000`。
- 消息 ID 由浏览器的 `crypto.randomUUID()` 生成。
- UI 保持简洁、专业、响应式；当前不使用复杂 UI 框架。

## 环境变量与 CORS

后端配置模板位于 `backend/.env.example`：

```text
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
FRONTEND_ORIGIN=http://localhost:5173
```

本地真实配置写入 `backend/.env`。该文件已被 `.gitignore` 忽略，不得读取、展示或提交其中的密钥。

FastAPI 当前只允许 `FRONTEND_ORIGIN` 指定的前端来源跨域访问。默认前端端口是 `5173`，默认后端端口是 `8000`；修改端口时要同步检查 CORS 和前端 API 地址。

## 本地开发

### 后端

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

只需在首次配置时创建虚拟环境和复制 `.env.example`。在 `backend/.env` 中填写真实的 `DEEPSEEK_API_KEY`，不要修改示例文件来保存密钥。

### 前端

```bash
cd frontend
npm install
npm run dev
```

浏览器默认访问 `http://localhost:5173`。

## 修改后的验证

前端改动至少执行：

```bash
cd frontend
npm run lint
npm run build
```

后端改动至少执行：

```bash
cd backend
.venv/bin/python -m compileall app
.venv/bin/python -c "from app.main import app; print(app.title)"
```

涉及真实聊天链路时，还应在用户已自行配置 API Key 的前提下启动前后端，验证 `/health` 和 `/api/chat`。测试和日志中不得输出 API Key。

## 代码与文件安全

- 修改前先检查当前工作区状态，保留用户已有改动。
- 优先沿用现有目录结构和编码风格，保持改动范围紧凑。
- 不提交 `.env`、虚拟环境、依赖目录、构建产物或缓存。
- 不通过清空目录或重建整个项目来解决局部问题。
- 不执行可能丢失用户改动的 Git 命令。
- 如需删除目录、多个文件或大量生成内容，先明确列出完整路径并取得用户确认。

## Git 状态

当前目录已经是 Git 仓库，默认分支为 `main`，远程仓库名为 `origin`。先前关于“当前目录不是 Git 仓库”的描述已经过期；执行工作时应以实时的 `git status` 结果为准。

## 当前已知环境说明

- 项目已经生成前端锁文件 `frontend/package-lock.json`，安装依赖时优先使用 npm 并保持锁文件同步。
- 当前依赖组合可以通过前端 lint 和生产构建。
- 开发机器曾使用 Node.js 19.8.1 完成验证，但依赖安装会提示引擎版本警告。日常开发建议使用受支持的 Node.js LTS 版本。
- 后端虚拟环境目录为 `backend/.venv/`，Python 源码可以通过编译和 FastAPI 应用导入检查。
