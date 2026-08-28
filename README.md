# Agent Echo

Agent 应用工程师 AI 模拟面试平台的本地垂直切片。

当前闭环：PDF/DOCX 简历解析 → AI 识别 Agent 项目 → 用户确认项目与个性化问题 → 8 题面试 → 回答持久化与基础报告。

## 目录

- `backend/`：FastAPI、SQLAlchemy、SQLite API。
- `frontend/`：Next.js 面试界面。
- `data/`：本地 SQLite 数据库和上传文件目录。
- `docs/superpowers/specs/`：已确认的垂直切片设计。

## 当前范围

面试保持 8 题：项目题 1～3、Agent 基础题 4～6、可靠性题 7～8；第 1、4、7 题分别是各组锚题。项目题可由硅基流动的 `deepseek-ai/DeepSeek-V4-Flash` 根据完整简历生成，并在用户确认后保存；没有使用 AI 分析时仍可手动填写并使用固定项目题。回答评估仍使用无需 API Key 的本地规则 Provider。

## 简历文件解析

首页支持上传 `.pdf` 和 `.docx` 文件，单文件上限为 10 MiB。文件会在本地解析为可编辑的简历文本，用户修改文本并确认项目事实后，才会创建面试会话。

支持的流程：

```text
上传 PDF / DOCX → 提取文本 → 编辑文本 → AI 分析（可选） → 确认项目与问题 → 开始面试
```

### AI 项目分析

上传并编辑简历后，点击“使用 AI 分析”。页面会先提示完整简历文本将发送给硅基流动；只有确认后才会调用模型。模型会选择一个最相关的 Agent 项目，提取项目事实并生成 3 道项目题。用户可以修改分析结果和问题，确认后再进入面试。

AI 配置只保存在本机的 `backend/.env`：

```powershell
Copy-Item backend/.env.example backend/.env
# 然后编辑 backend/.env，填写自己的 SILICONFLOW_API_KEY
```

`backend/.env` 已被 Git 忽略，不能提交到仓库。不要把 API Key 写入前端或命令行；如果密钥曾经暴露，应在硅基流动后台撤销并重新生成。

上传文件保存在 `data/uploads/`，该目录已加入 Git 忽略规则。扫描型 PDF、图片简历和只有图片的 DOCX 暂不支持 OCR，请改用文本粘贴或手动录入。

## 本地运行

在项目根目录打开 PowerShell：

```powershell
python -m venv backend/.venv
backend\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python -m uvicorn app.main:app --reload --port 8000" -WorkingDirectory "$PWD\backend"
npm --prefix frontend install
npm --prefix frontend run dev
```

浏览器访问 `http://localhost:3000`；API 健康检查为 `http://localhost:8000/health`；本地 SQLite 文件为 `data/app.db`。

## Git 日常更新

```powershell
git add .
git commit -m "描述本次修改"
git push
```
