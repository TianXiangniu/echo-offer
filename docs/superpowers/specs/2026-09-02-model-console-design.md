# Echo Offer 模型控制台设计

## 1. 目标

为本地单用户版本增加一个网页端模型控制台，让用户能够查看和修改后续简历分析、面试评分使用的模型参数。配置保存到本地 SQLite，保存后立即生效，重启服务后仍然保留。

本次只解决模型配置管理，不增加账号体系、远程配置中心、配置版本回滚或多用户权限。

## 2. 用户侧体验

入口为首页的“设置”链接，页面路径为 /console。

页面分为三个区域：

- 模型服务：API 地址、分析模型、评分模型、API Key 输入框、连接测试；
- 生成参数：温度、最大输出长度、请求超时时间、每批评分题目数量；
- 当前状态：当前模型、Key 是否已配置、最近一次测试结果、最近一次保存时间。

页面沿用现有的轻量卡片布局，不使用密集的后台管理表格。主要操作只有：

- 保存并应用：保存配置并立即刷新后端运行时配置；
- 测试连接：使用低输出上限发起一次最小模型请求；
- 恢复默认：把参数恢复为应用默认值，但不自动清空 API Key。

保存成功后显示“设置已保存，后续请求将使用新配置”。连接失败时显示可操作的具体原因。

## 3. 配置模型

新增本地表 model_settings，每个本地用户只有一条生效配置：

- id
- user_id，唯一索引；
- base_url
- model
- assessment_model
- temperature
- max_tokens
- timeout_seconds
- assessment_batch_size
- api_key，仅供后端本地使用；
- updated_at

配置查询接口永远不返回 api_key。只返回 api_key_configured: boolean。更新请求中 API Key 为空时保留旧值；只有显式传入 clear_api_key: true 才清空旧值。

这是本地单用户 Alpha 方案，数据库文件仍属于本机用户。后续如果做多用户部署，需要把 API Key 改成系统密钥存储或加密字段，不能直接沿用本地明文存储方案。

## 4. 接口

### GET /api/settings/model

返回当前有效配置，不返回 API Key。示例：

    {
      "base_url": "https://api.siliconflow.cn/v1",
      "model": "deepseek-ai/DeepSeek-V4-Flash",
      "assessment_model": "deepseek-ai/DeepSeek-V4-Flash",
      "temperature": 0.1,
      "max_tokens": 2400,
      "timeout_seconds": 90,
      "assessment_batch_size": 3,
      "api_key_configured": true,
      "updated_at": "..."
    }

### PUT /api/settings/model

更新并应用配置。参数范围由后端校验：

- temperature：0 到 2；
- max_tokens：256 到 8192；
- timeout_seconds：10 到 300；
- assessment_batch_size：1 到 5。

配置无效时返回字段级错误，不写入部分结果。

### POST /api/settings/model/test

使用当前已保存配置，发送一次最小 JSON 请求，返回：

- ok
- message
- model
- latency_ms
- error_code（失败时）

测试请求不保存模型返回原文，不写入面试评分或用户画像。

## 5. 运行时生效方式

启动时读取数据库中的模型配置；不存在时使用现有环境变量和默认值初始化。

保存配置时：

1. 在同一个数据库事务中校验并写入配置；
2. 重新构造简历分析 Provider 和面试评分 Provider；
3. 替换 app.state 中的运行时 Provider；
4. 提交事务后返回脱敏配置。

后续请求从 app.state 使用新的 Provider，因此不需要重启服务。若保存过程失败，数据库和运行时 Provider 都保持旧配置。

配置优先级为：

    数据库已保存配置 > 环境变量 > 应用默认值

## 6. 错误处理

统一使用稳定错误码：

- invalid_settings：参数超出范围或地址格式错误；
- provider_not_configured：没有配置 API Key；
- provider_auth_failed：Key 无效或无权限；
- provider_timeout：请求超过超时时间；
- provider_connection_failed：无法连接 API 地址；
- provider_http_error：模型服务返回其他 HTTP 错误；
- invalid_model_response：测试请求返回结构异常。

前端不展示后端异常堆栈，也不展示 API Key。网络错误、认证错误和超时错误分别给出下一步操作提示。

## 7. 前端设计

控制台延续现有页面的品牌和排版：

- 页面顶部保留品牌名和返回入口；
- 参数采用两列卡片，在窄屏自动变为单列；
- 温度、输出长度、超时时间和批量大小使用数字输入并显示范围提示；
- API Key 使用密码输入框，保存后显示“已配置”，不回填原值；
- 保存期间禁用重复提交，测试期间显示“正在测试连接…”；
- 成功和失败状态使用页面内提示，不使用浏览器 alert。

## 8. 测试策略

后端：

- 配置默认值加载；
- 配置范围校验；
- API Key 不出现在 GET 响应；
- 空 API Key 保留旧值，显式清除才删除；
- 配置保存后 Provider 使用新参数；
- 测试接口映射认证、超时、连接和响应结构错误；
- 数据库迁移和单用户唯一约束。

前端：

- 配置响应类型和脱敏字段；
- 表单默认值、范围提示和保存状态；
- API Key 不回填；
- 测试失败时展示稳定的中文提示；
- 生产构建通过。

