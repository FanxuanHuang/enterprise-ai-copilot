# Enterprise AI Copilot

Enterprise AI Copilot 是一个分阶段构建的企业级 AI 助手求职作品集项目。

当前 V1 只实现最基础的 Full Stack LLM 链路：

```text
React + TypeScript
  -> HTTP API
  -> FastAPI / Python
  -> DeepSeek OpenAI-compatible API
  -> FastAPI
  -> React 展示回答
```

V1 暂不包含 RAG、向量数据库、LangGraph、Tool Calling、MCP、Memory、PostgreSQL、Docker 或用户登录。

## 当前 V1 架构

- `frontend/`: React + TypeScript + Vite 聊天界面
- `backend/`: FastAPI 后端服务
- `backend/app/api/`: API 路由
- `backend/app/core/`: 配置读取
- `backend/app/schemas/`: 请求和响应模型
- `backend/app/services/`: LLM 调用逻辑

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

## 当前目录结构

```text
enterprise-ai-copilot/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── chat.py
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   └── config.py
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   └── chat.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   └── llm_service.py
│   │   ├── __init__.py
│   │   └── main.py
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

