# Agent Echo

Agent 应用工程师 AI 模拟面试平台的本地垂直切片。

当前闭环：PDF/DOCX 简历解析 → AI 识别 Agent 项目 → 用户确认项目与个性化问题 → 8 题面试 → AI 盲评分 → 证据报告。

## 目录

- `backend/`：FastAPI、SQLAlchemy、SQLite API。
- `frontend/`：Next.js 面试界面。
- `data/`：本地 SQLite 数据库和上传文件目录。
- `docs/superpowers/specs/`：已确认的垂直切片设计。

## 当前范围

面试保持 8 题：项目题 1～3、Agent 基础题 4～6、可靠性题 7～8；第 1、4、7 题分别是各组锚题。项目题可由硅基流动的 `deepseek-ai/DeepSeek-V4-Flash` 根据完整简历生成，并在用户确认后保存；没有使用 AI 分析时仍可手动填写并使用固定项目题。回答阶段只保存首答，不调用评分模型；全部问题完成后由 SiliconFlow 盲评分器一次性批量返回各题的冻结 Rubric 评分，程序校验证据并聚合 0～4 等级。模型失败时回答仍会保存为待评估状态，不会被伪造为 0 分。

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

`backend/.env` 已被 Git 忽略，不能提交到仓库。不要把 API Key 写入前端、日志或 Git；如果密钥曾经暴露，应在硅基流动后台撤销并重新生成。

### 模型设置控制台

启动前后端后，打开 `http://localhost:3000/console` 可以在网页中查看和修改服务地址、项目整理模型、面试评分模型、温度、最大输出长度、请求超时时间和每批评分题目数量。

填写 API Key 后点击“保存并应用”，设置会保存在本机的 SQLite 数据库中，并立即用于后续请求。读取设置时只显示“是否已配置”，不会返回 API Key；API Key 输入框留空保存会保留原值。修改设置后可点击“测试连接”确认当前已保存的服务是否可用。若模型回答达到长度上限，优先适当提高“最大输出长度”。

### 面试记录

打开 `http://localhost:3000/history` 可以查看本机保存的面试记录。未完成的记录可以继续，完成且有报告的记录可以查看结果，评分失败的记录可以重新生成。删除记录只会从历史列表中隐藏，不会在 Alpha 阶段物理删除回答和报告。

上传文件保存在 `data/uploads/`，该目录已加入 Git 忽略规则。扫描型 PDF、图片简历和只有图片的 DOCX 暂不支持 OCR，请改用文本粘贴或手动录入。

## 本地运行

在项目根目录打开 PowerShell：

```powershell
python -m venv backend/.venv
backend\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
npm --prefix frontend install
npm --prefix frontend run dev
```

首次配置 AI 评分时，复制 `backend/.env.example` 为 `backend/.env`，只在本地填写密钥和模型配置：

```powershell
Copy-Item backend/.env.example backend/.env
# 编辑 backend/.env，填写 SILICONFLOW_API_KEY
```

启动后端时，从项目根目录执行：

```powershell
python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

如果后端使用 8010 端口，启动前设置：

```powershell
$env:NEXT_PUBLIC_API_URL="http://127.0.0.1:8010"
```

浏览器访问 `http://localhost:3000`；API 健康检查为 `http://localhost:8000/health`；本地 SQLite 文件为 `data/app.db`。

## AI 评分说明

评估器标识为 `siliconflow-blind-rubric-v1`。它只接收当前问题、冻结 Rubric、允许的参考事实和当前回答，不读取简历原文、历史回答或过去分数。

每道题按 correctness、mechanism、scenario、engineering 四个 Rubric 项评分。程序会校验证据字符区间和回答 SHA-256，再按固定公式聚合为 0～4 等级。报告展示等级、覆盖率、有效证据数、置信度、优势和缺口，不展示未经校准的 0～100 总分。

回答过程中不会触发 AI 评分；最后一题提交后，一场面试只发起一次批量评估请求。页面会显示收集回答、请求模型、校验证据、生成报告四个阶段。模型超时或网络失败时，回答不会丢失，可以在完成页或报告页重新生成评估，重试不会增加回答记录。当前阶段暂不包含证据语义相关性验证、技术事实核验、追问器和 AI 评分 SSE。

## 面试历史与用户画像

每次开始面试都会创建新的面试记录。题目、回答、AI 评分、评分重试和报告版本都保存在 `data/app.db`，不会覆盖之前的面试。服务重启后仍可以通过历史接口读取过去的面试。

批量评分完成且结果有效后，系统会按技能汇总最近的面试结果，更新当前求职方向的用户画像，并生成学习建议。单场评分不读取历史画像；长期趋势分析只使用已经保存的结构化评分。

每次整场评分都会记录一个独立的 `assessment_batch` 和 `operation_job`。评分阶段、完成或失败信息会写入 `operation_job_events`，因此可以通过 `GET /api/jobs/{job_id}` 查看本次分析过程和错误原因。面试历史使用 `GET /api/interviews/history`，画像摘要使用 `GET /api/profiles/{profile_id}/summary`，画像快照使用 `GET /api/profiles/{profile_id}/history`。

浏览器访问 `http://localhost:3000/profile` 可以查看用户画像。页面会按求职方向整理能力等级、有效回答次数、变化记录和练习建议；建议状态可以直接更新。薄弱项会按“优先回看、接着练、再答几次看看”整理，并可跳回对应面试报告；记录不足时会直接说明，不把缺失记录当成答错。查看或切换画像只读取本地数据库，不会额外调用模型。

数据库结构通过 Alembic 管理。需要手动执行迁移时，在项目根目录运行：

```powershell
Set-Location backend
python -m alembic -c alembic.ini upgrade head
Set-Location ..
```

本地数据库备份可以调用 `backend/app/backup.py` 中的 `backup_database`，备份文件保存到 `data/backups/`，使用 SQLite Online Backup API，包含 WAL 中尚未合并的数据，不会自动删除旧备份。

## Git 日常更新

本阶段只保留本地代码和本地提交，不会自动同步到 GitHub。确认需要提交本地版本时，再按文件范围执行 `git add` 和 `git commit`；推送命令由你明确决定后再执行。
