# Model Console Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a local model console that persists model settings in SQLite, applies them to later resume analysis and batch assessment requests immediately, and lets the user test the current connection without exposing the API Key.

**Architecture:** Add one local-user model settings row and a small settings service that merges database values with environment defaults. The FastAPI app keeps the effective settings and providers in app.state; saving settings commits first and then swaps providers, while the connection probe uses the same effective settings without creating assessment or profile records. Add a /console Next.js page that talks to these endpoints and follows the existing lightweight visual language.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, Alembic, SQLite, httpx, Next.js 15, React, TypeScript, existing mint UI styles.

## Global Constraints

- The app remains a local single-user Alpha; use LOCAL_USER_ID and do not add authentication or multi-user permissions.
- The database is SQLite and schema changes must use Alembic.
- GET settings responses must never contain the API Key; they may only contain api_key_configured.
- An empty API Key in an update keeps the old value; only clear_api_key=true clears it.
- Valid ranges are temperature 0-2, max_tokens 256-8192, timeout_seconds 10-300, and assessment_batch_size 1-5.
- Saving settings must apply to later requests without restarting the service.
- A connection test must not save raw model output or create interview, assessment, report, or profile records.
- Do not print, log, commit, or push any real API Key.
- Preserve existing user-owned UI and documentation changes outside this feature.

---

### Task 1: Add the persisted model settings contract

**Files:**
- Create: backend/app/model_settings.py
- Create: backend/alembic/versions/0004_model_settings.py
- Modify: backend/app/models.py: add ModelSetting after User
- Modify: backend/app/schemas.py: add model settings request/response schemas
- Test: backend/tests/test_model_settings.py

**Interfaces:**
- Produces ModelSettingsValues, load_model_settings(db), save_model_settings(db, payload), and public_model_settings(settings).
- ModelSettingsValues contains base_url, model, assessment_model, api_key, temperature, max_tokens, timeout_seconds, assessment_batch_size.
- The API response contains base_url, model, assessment_model, temperature, max_tokens, timeout_seconds, assessment_batch_size, api_key_configured, and updated_at.
- The update request contains optional API Key, clear_api_key, and all editable values.

- [ ] **Step 1: Write failing tests for defaults, masking, and update semantics**

    Add tests that create a temporary database, call load_model_settings with no row, and assert the environment defaults are returned. Add tests that save an API Key and assert public_model_settings contains api_key_configured=true but does not contain the key. Add tests that update with api_key="" and clear_api_key=false preserves the old key, while clear_api_key=true removes it. Add range tests for temperature=-0.1, max_tokens=100, timeout_seconds=9, and assessment_batch_size=6.

- [ ] **Step 2: Run the focused tests and verify they fail**

    Run: python -m pytest backend/tests/test_model_settings.py -q

    Expected: FAIL because the settings model and service do not exist.

- [ ] **Step 3: Add the SQLAlchemy model and Alembic migration**

    Add a ModelSetting table with one unique user_id row and columns id, user_id, base_url, model, assessment_model, temperature, max_tokens, timeout_seconds, assessment_batch_size, api_key, and updated_at. The migration must create the table and downgrade must drop it. Use String/Text/Integer/DateTime types consistent with backend/app/models.py and add a foreign key to users.id.

- [ ] **Step 4: Implement defaults, validation, persistence, and redacted serialization**

    In backend/app/model_settings.py, define a frozen dataclass:

    ModelSettingsValues(base_url: str, model: str, assessment_model: str, api_key: str, temperature: float, max_tokens: int, timeout_seconds: float, assessment_batch_size: int, updated_at: datetime | None = None)

    Implement defaults from config values, load the LOCAL_USER_ID row or return defaults, and validate the exact numeric ranges from Global Constraints. Reject an empty base URL, model, or assessment model. save_model_settings must preserve api_key when the request key is blank, honor clear_api_key, update the single row, and return the effective values. public_model_settings must omit the api_key field entirely.

- [ ] **Step 5: Run the focused tests and verify they pass**

    Run: python -m pytest backend/tests/test_model_settings.py -q

    Expected: PASS.

- [ ] **Step 6: Commit the isolated settings persistence work**

    Run:

    git add backend/app/model_settings.py backend/app/models.py backend/app/schemas.py backend/alembic/versions/0004_model_settings.py backend/tests/test_model_settings.py
    git commit -m "feat: persist local model settings"

### Task 2: Make provider requests use runtime settings and add a safe connection probe

**Files:**
- Modify: backend/app/providers.py: SiliconFlowProjectAnalysisProvider, SiliconFlowAssessmentProvider, and shared request helpers
- Modify: backend/app/config.py: expose the default max token value if needed
- Test: backend/tests/test_providers.py
- Test: backend/tests/test_model_settings.py or backend/tests/test_settings_api.py for probe behavior

**Interfaces:**
- Provider constructors accept temperature, max_tokens, timeout_seconds, and keep existing model/base_url/api_key arguments.
- Add probe_model_connection(settings, client=None) -> dict with ok, message, model, latency_ms, and optional error_code.
- The probe must use the same base URL, API Key, model, timeout, and temperature as the saved settings, but max_tokens is fixed to a small value such as 16.

- [ ] **Step 1: Write failing provider tests for parameter propagation**

    Extend the mock HTTP tests to construct both providers with temperature=0.7 and max_tokens=4800, call analyze and assess_batch, and assert the outgoing JSON contains those values. Add a probe test that asserts the request uses max_tokens=16 and that the returned latency is a non-negative integer. Add probe tests for missing API Key, 401, timeout, connection failure, and malformed response.

- [ ] **Step 2: Run the focused provider tests and verify they fail**

    Run: python -m pytest backend/tests/test_providers.py -q

    Expected: FAIL because the constructors currently hard-code temperature and token limits and no probe exists.

- [ ] **Step 3: Parameterize all SiliconFlow request payloads**

    Store temperature, max_tokens, and timeout_seconds on both provider instances. Use the configured max_tokens for project analysis, single assessment, and batch assessment. Keep the existing batch prompt/chunking behavior; the console controls the per-request output ceiling. Preserve the current response extraction, truncation detection, and parser error codes.

- [ ] **Step 4: Implement the connection probe without persistence side effects**

    Add a helper that validates the API Key, posts a minimal JSON-mode request to base_url/chat/completions, measures elapsed milliseconds with a monotonic clock, maps HTTP/timeout/request/response errors to the existing stable provider codes, and returns only redacted metadata. Never include response content, request headers, or the API Key in the return value or logs.

- [ ] **Step 5: Run focused tests and verify they pass**

    Run: python -m pytest backend/tests/test_providers.py -q

    Expected: PASS.

- [ ] **Step 6: Commit the provider runtime work**

    Run:

    git add backend/app/providers.py backend/app/config.py backend/tests/test_providers.py
    git commit -m "feat: apply runtime model parameters"

### Task 3: Add settings API and immediate runtime refresh

**Files:**
- Modify: backend/app/main.py: provider construction, settings routes, error mapping
- Modify: backend/app/services.py or create backend/app/model_settings.py: runtime provider factory/update helper
- Test: backend/tests/test_settings_api.py
- Test: backend/tests/conftest.py only if fixtures need a settings-aware app

**Interfaces:**
- GET /api/settings/model returns the redacted effective settings.
- PUT /api/settings/model accepts ModelSettingsUpdate and returns ModelSettingsResponse.
- POST /api/settings/model/test returns ModelConnectionTestResponse.
- Add refresh_model_providers(app, settings) that constructs the analysis and assessment providers from one effective settings snapshot.

- [ ] **Step 1: Write failing API tests**

    Add tests that call GET and assert default fields plus api_key_configured=false without an api_key field. Add a PUT test that saves model="test-model", temperature=0.7, max_tokens=4800, timeout_seconds=120, assessment_batch_size=2, then asserts the response values and that app.state.assessment_provider and app.state.project_analysis_provider carry the new values. Add tests for invalid ranges returning 422 and leaving the previous settings unchanged. Add a test that PUT with a new API Key does not return it. Add test endpoint success and provider failure mappings.

- [ ] **Step 2: Run the focused API tests and verify they fail**

    Run: python -m pytest backend/tests/test_settings_api.py -q

    Expected: FAIL because the routes and runtime refresh do not exist.

- [ ] **Step 3: Load database settings during app creation**

    After create_database returns its session factory, load the local settings row. If no row exists, use environment defaults. Keep injected fake providers unchanged in tests; only construct production providers from the effective settings when the caller did not provide one. Store the effective settings in app.state.model_settings.

- [ ] **Step 4: Implement the three settings routes**

    GET calls load_model_settings and returns public_model_settings. PUT validates the request, builds replacement providers before committing, saves the row, commits the database transaction, then swaps app.state.model_settings and both providers. If validation or commit fails, leave the old runtime providers in place. POST loads app.state.model_settings, calls probe_model_connection, and returns the probe metadata. Add a stable exception handler/status mapping for invalid_settings and all provider probe codes.

- [ ] **Step 5: Run the focused API tests and verify they pass**

    Run: python -m pytest backend/tests/test_settings_api.py -q

    Expected: PASS.

- [ ] **Step 6: Run the full backend suite**

    Run: python -m pytest backend/tests -q

    Expected: PASS with the existing tests plus the new settings tests.

- [ ] **Step 7: Commit the backend settings API**

    Run:

    git add backend/app/main.py backend/app/model_settings.py backend/app/schemas.py backend/tests/test_settings_api.py
    git commit -m "feat: add model settings API"

### Task 4: Build the /console page and connect it to the API

**Files:**
- Modify: frontend/lib/api.ts: add model settings types and get/update/test functions
- Create: frontend/app/console/page.tsx
- Modify: frontend/app/page.tsx: add the settings entry point
- Modify: frontend/app/globals.css: add console-specific styles
- Create: frontend/lib/model-console.test.ts

**Interfaces:**
- getModelSettings() -> Promise<ModelSettingsResponse>
- updateModelSettings(payload: ModelSettingsUpdate) -> Promise<ModelSettingsResponse>
- testModelConnection() -> Promise<ModelConnectionTestResponse>

- [ ] **Step 1: Write failing frontend contract tests**

    Add a test that checks the API types include api_key_configured and never require api_key in the response. Add a copy/markup contract test that requires /console, “保存并应用”, “测试连接”, “恢复默认”, “API Key”, “最大输出长度”, “请求超时时间”, and “每批评分题目数量”.

- [ ] **Step 2: Run the focused frontend test and verify it fails**

    Run: npm run test:model-console

    Expected: FAIL because the console page, API helpers, and script do not exist.

- [ ] **Step 3: Add API client functions and types**

    Add the exact settings request/response types, parse errors through the existing ApiError path, and implement GET/PUT/POST calls against the backend. The update payload should send the API Key only when the user typed a new value; an empty field must not overwrite the stored key.

- [ ] **Step 4: Implement the console page**

    Load settings on mount. Render a calm two-column page using the existing mint-shell, mint-header, mint-card, mint-field, mint-button, mint-alert, and mint-note styles. Use a password input for the API Key with helper copy “已配置时不会回填，留空表示保持不变”. Add numeric inputs with min/max/step values, a checkbox or explicit action for clear_api_key, and the three actions from the spec. Disable duplicate submits, show inline success/error messages, and never render a returned API Key value because none is returned.

- [ ] **Step 5: Add the home entry point and responsive styles**

    Add a small “模型设置” link near the existing home navigation. Add console-specific styles for the section grid, field descriptions, status pill, action row, and mobile single-column layout. Preserve visible focus states and the existing reduced-motion rules.

- [ ] **Step 6: Run the focused frontend test and verify it passes**

    Add test:model-console: node --experimental-strip-types lib/model-console.test.ts to frontend/package.json and run npm run test:model-console.

    Expected: PASS.

- [ ] **Step 7: Run all frontend tests and the production build**

    Run: npm test

    Expected: PASS.

    Run: npm run build

    Expected: PASS with the /console route included.

- [ ] **Step 8: Commit the console UI**

    Run:

    git add frontend/lib/api.ts frontend/app/console/page.tsx frontend/app/page.tsx frontend/app/globals.css frontend/lib/model-console.test.ts frontend/package.json
    git commit -m "feat: add model settings console"

### Task 5: Document local use and complete verification

**Files:**
- Modify: README.md: add console route and startup/testing instructions
- Test: backend/tests and frontend tests

- [ ] **Step 1: Add concise README instructions**

    Document opening http://localhost:3000/console, saving the API Key, setting max_tokens higher when a response is truncated, and using Test Connection. State that the API Key is stored locally for this single-user Alpha and is never returned by the GET endpoint. Do not include any real Key in the README.

- [ ] **Step 2: Run final verification**

    Run:

    python -m pytest backend/tests -q
    npm test from frontend
    npm run build from frontend
    git diff --check

    Expected: all tests and build pass; diff check has no whitespace errors. LF/CRLF notices on Windows are acceptable and are not test failures.

- [ ] **Step 3: Inspect the final working tree**

    Run: git status --short

    Verify that only the intended local changes are present and that no API Key appears in the diff. Do not run git push.

