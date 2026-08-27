# Agent Echo

Agent 应用工程师 AI 模拟面试平台的本地垂直切片。

当前闭环：简历文本与项目确认 → 固定 8 题面试 → 回答持久化与恢复 → 基础报告。

## 目录

- `backend/`：FastAPI、SQLAlchemy、SQLite API。
- `frontend/`：Next.js 面试界面。
- `data/`：本地 SQLite 数据库和上传文件目录。
- `docs/superpowers/specs/`：已确认的垂直切片设计。

## 当前范围

题目固定为项目深挖 3 题、Agent 基础 3 题、工程故障排查 2 题；评估使用无需 API Key 的本地规则 Provider。简历支持文本粘贴、文本型 PDF 和 DOCX 解析；扫描 PDF、图片 OCR、DeepSeek、LangGraph、训练复盘和延迟验证暂不包含在本切片中。

## 简历文件解析

首页支持上传 `.pdf` 和 `.docx` 文件，单文件上限为 10 MiB。文件会在本地解析为可编辑的简历文本，用户修改文本并确认项目事实后，才会创建面试会话。

支持的流程：

```text
上传 PDF / DOCX → 提取文本 → 编辑文本 → 确认项目 → 开始面试
```

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
