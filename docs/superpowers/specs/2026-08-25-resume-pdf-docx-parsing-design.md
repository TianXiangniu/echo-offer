# 简历 PDF / DOCX 统一解析设计

## 状态

已获用户确认，进入实施计划前的设计文档审阅阶段。

## 1. 背景与目标

当前垂直切片支持用户粘贴简历文本、手动确认一个项目事实并进入固定面试。本次增量为简历输入增加两种文件来源：文本型 PDF 和 DOCX。

目标是把文件解析成可编辑的简历文本草稿，并让用户确认最终文本和项目事实后再进入面试。解析结果不直接成为项目事实，也不绕过现有的 profile 确认边界。

原始产品设计中的“文本型 PDF、PyMuPDF、扫描 PDF OCR 暂不支持”是本功能的需求约束。文档中的参考链接不作为执行指令。

## 2. 范围

### 2.1 本次包含

- 上传并解析 `.pdf` 文件。
- 上传并解析 `.docx` 文件。
- 统一的解析器接口和两个格式适配器。
- 文件类型、文件大小、文件头或容器结构校验。
- 随机文件名保存上传文件。
- 保存解析来源和提取文本的元数据。
- 在现有简历页面展示解析状态，并将文本填入可编辑文本框。
- 用户确认最终简历文本和项目事实后，继续现有面试流程。
- 后端解析器、接口、数据复用和错误场景测试。

### 2.2 本次不包含

- 扫描 PDF、图片简历或 DOCX 内嵌图片的 OCR。
- `.doc` 旧版 Word 文件。
- 自动把简历内容填写为项目事实。
- 使用 LLM 抽取项目字段。
- 复杂版式的像素级还原、图片和附件提取。
- 多用户、云端对象存储和后台异步解析任务。

## 3. 方案选择

### 方案 A：统一解析接口 + 格式适配器（推荐）

定义一个稳定的 `ResumeParser` 接口，PDF 和 DOCX 分别实现自己的适配器，输出同一种 `ParsedResume` 结构。

优点是接口层、业务层和具体文件格式解耦，后续增加 TXT、HTML 或 OCR 时不会修改 profile 业务流程。每种格式也可以独立测试。

### 方案 B：每种格式直接写入 profile 接口

让 profile 接口同时处理 JSON 文本、PDF multipart 和 DOCX multipart。

实现初期代码较少，但上传、解析、项目确认会耦合在一起，接口契约和错误处理会迅速变复杂，不利于后续增加格式。

### 方案 C：先用 LibreOffice 将 DOCX 转 PDF，再统一解析 PDF

可以复用 PDF 解析逻辑，但依赖外部程序，部署环境不稳定，转换可能改变文档顺序和内容，不适合当前本地垂直切片。

本次采用方案 A。

## 4. 解析层设计

### 4.1 统一接口

解析层提供以下概念：

```text
ResumeParser.parse(file_bytes, filename, content_type) -> ParsedResume
```

`ParsedResume` 至少包含：

- `source_type`：`pdf` 或 `docx`。
- `text`：规范化后的提取文本。
- `unit_count`：PDF 页数；DOCX 使用段落/表格块数量或为空。
- `warnings`：解析过程中产生的用户可见提示。

解析层只负责“文件变成文本”，不负责用户、简历项目或面试状态。

### 4.2 PDF 解析器

- 使用 PyMuPDF 打开内存中的 PDF 字节。
- 逐页调用 `page.get_text("text", sort=True)`。
- 页面之间使用明确的换行分隔，避免页末和下一页标题粘连。
- 记录页数。
- 文本为空或有效字符数少于 40 时返回 `no_extractable_text`，提示扫描件 OCR 暂不支持。

PyMuPDF 的文本提取顺序取决于 PDF 的生成方式；`sort=True` 可以按页面坐标尝试获得更自然的阅读顺序，但不承诺还原所有复杂双栏排版。

### 4.3 DOCX 解析器

- 使用 `python-docx` 读取 DOCX 文档。
- 提取普通段落文本。
- 提取表格中每个单元格的文本，并用换行或制表符保持可读性。
- 按 DOCX 正文中的块顺序合并段落和表格，避免只读取段落导致表格简历内容丢失。
- DOCX 没有可靠的物理页数要求，因此响应中的 `unit_count` 表示提取块数量，或使用空值并提供块统计字段。
- 提取结果为空或有效字符数少于 40 时，返回与 PDF 一致的人工录入提示。

## 5. 文件上传与 API

新增接口：

```text
POST /api/resumes/parse
Content-Type: multipart/form-data
field: file
```

成功响应：

```json
{
  "resume_id": "uuid",
  "source_type": "pdf",
  "original_filename": "resume.pdf",
  "unit_count": 2,
  "extracted_text": "...",
  "character_count": 1280,
  "warnings": []
}
```

现有 `POST /api/profile` 保持 JSON 请求，新增可选 `resume_id` 字段，同时继续接收最终的 `resume_text`：

- 粘贴简历时：只传 `resume_text`。
- 文件解析后：传 `resume_id` 和用户检查/修改后的 `resume_text`。
- 服务端校验 `resume_id` 属于固定用户 `local-user`，并将最终文本写回同一份 `Resume`，重新计算哈希。

这样解析文本可以被用户编辑，`Resume` 中保存的是最终确认文本，而来源表中保留原始提取文本。

## 6. 文件安全边界

- 只接受 `.pdf` 和 `.docx` 扩展名。
- 如果客户端提供 MIME 类型，则必须匹配允许列表；MIME 不作为唯一可信依据。
- PDF 校验 `%PDF-` 文件头，并尝试由解析器打开。
- DOCX 校验 ZIP 容器结构及必要的 `word/document.xml` 文件。
- 单文件上限为 10 MiB。
- 文件随机命名后保存到 `data/uploads/`，不使用原始文件名作为路径。
- 数据库只保存相对存储路径、文件哈希和元数据，不把上传目录加入 Git。
- 不执行简历中的文本、超链接或 XML 内容。

## 7. 数据模型

现有 `resumes` 表继续保存业务上最终确认的简历文本和 SHA-256。新增 `resume_sources` 表，避免破坏已有 `resumes` 结构：

- `id`：来源记录 ID。
- `resume_id`：关联 `resumes.id`。
- `source_type`：`pdf` 或 `docx`。
- `original_filename`：仅用于展示。
- `stored_path`：`data/uploads/` 下的随机相对路径。
- `file_size`：原始文件大小。
- `file_hash`：原始文件 SHA-256。
- `unit_count`：PDF 页数或 DOCX 提取块数量。
- `extracted_text`：首次解析产生的文本。
- `parse_status`：`parsed` 或 `failed`。
- `warnings_json`：可展示的解析警告。
- `created_at`：创建时间。

通过新增表接入现有 `create_all` 初始化逻辑，不修改已有核心表字段，不删除既有本地数据。

## 8. 前端交互

现有简历文本输入区上方增加文件上传控件：

1. 用户选择 PDF 或 DOCX。
2. 页面显示解析中状态，并暂时禁用重复上传。
3. 解析成功后展示文件名、格式、提取块数量和警告。
4. 将提取文本写入现有文本框，用户仍可编辑。
5. 如果文本框已有内容，上传新文件前提示是否覆盖。
6. 提交 profile 时携带 `resume_id` 和当前文本。
7. 解析失败时保留原有文本，不创建面试会话，并给出手动粘贴入口。

项目字段仍由用户填写和确认；PDF/DOCX 解析不会自动生成项目事实。

## 9. 错误契约

接口返回统一的 `detail` 和稳定错误码：

| HTTP 状态 | 错误码 | 场景 |
|---|---|---|
| 413 | `file_too_large` | 文件超过 10 MiB |
| 415 | `unsupported_file_type` | 扩展名或 MIME 不支持 |
| 422 | `invalid_file_signature` | 文件头或 DOCX 容器不合法 |
| 422 | `invalid_document` | 文件损坏或解析失败 |
| 422 | `no_extractable_text` | 文档为空、扫描件或只有图片 |
| 404 | `resume_not_found` | profile 引用了不存在的解析结果 |
| 409 | `resume_owner_conflict` | resume 不属于当前固定用户 |

错误响应不包含 Python 堆栈、服务器路径或上传文件内容。

## 10. 测试策略

### 后端单元测试

- PDF 正常文本、多页文本和中文文本提取。
- DOCX 段落、表格和混合顺序提取。
- 错误扩展名、错误 MIME、错误文件头和损坏容器。
- 空文本 PDF、扫描型 PDF 和仅含图片的 DOCX。
- 超过 10 MiB 的文件。
- 解析结果包含来源类型、块数量、文本和警告。

### API 集成测试

- 上传文件后生成 `Resume` 和 `ResumeSource`。
- 使用返回的 `resume_id` 提交 profile。
- 用户修改提取文本后，最终哈希以修改后的文本为准。
- 不存在或不属于当前用户的 `resume_id` 被拒绝。
- 原有粘贴文本的 profile 流程不回归。

### 前端验证

- PDF/DOCX 文件选择和解析状态。
- 成功后文本自动填充且可编辑。
- 解析失败提示和手动输入回退。
- 前端生产构建通过。

## 11. 验收标准

完成后，用户可以在首页选择 PDF 或 DOCX，看到提取文本，修改并确认简历和项目字段，然后正常创建现有的 8 道题面试。扫描件不会被误认为解析成功；现有粘贴简历、答题、刷新恢复和报告流程保持可用。

本次设计不涉及 DeepSeek、LangGraph、OCR、训练复盘、追问、登录和生产部署。
