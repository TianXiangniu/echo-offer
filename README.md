# Agent Echo

Agent 应用工程师 AI 模拟面试平台的本地垂直切片。

当前闭环：简历文本与项目确认 → 固定 8 题面试 → 回答持久化与恢复 → 基础报告。

## 目录

- `backend/`：FastAPI、SQLAlchemy、SQLite API。
- `frontend/`：Next.js 面试界面。
- `data/`：本地 SQLite 数据库目录。
- `docs/superpowers/specs/`：已确认的垂直切片设计。

## 当前范围

题目固定为项目深挖 3 题、Agent 基础 3 题、工程故障排查 2 题；评估使用无需 API Key 的本地规则 Provider。PDF、DeepSeek、LangGraph、训练复盘和延迟验证暂不包含在本切片中。

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
