"""金标集校准：用标注回答跑评分器，输出每个知识点的 MAE。

用法（在项目根目录）：
    backend\\.venv\\Scripts\\python.exe scripts/eval_scorer.py --provider fake   # 离线冒烟
    backend\\.venv\\Scripts\\python.exe scripts/eval_scorer.py           # 真实调用，需已配置 API Key

规矩：任何评分 prompt 变更，先跑一遍金标集对比版本 MAE 再上线。
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "backend"))

from app.assessment_engine import (  # noqa: E402
    AssessmentResponseError,
    aggregate_assessment,
    parse_batch_model_assessment,
)
from app.question_bank import QUESTION_TEMPLATES, QuestionSpec  # noqa: E402


def load_golden(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build_spec(row: dict) -> QuestionSpec:
    knowledge_point_id = row["knowledge_point_id"]
    template = (QUESTION_TEMPLATES.get(knowledge_point_id) or (None,))[0]
    return QuestionSpec(
        order=1,
        category="reliability",
        is_anchor=False,
        prompt=row["question"],
        knowledge_point_id=knowledge_point_id,
        rubric_version="alpha-local-v1",
        signals=template.signals if template else ("评估",),
        reference_facts=template.reference_facts if template else (),
        template_id=template.template_id if template else "",
        rubric_weights=template.rubric_weights if template else (),
        criteria_override=template.criteria_override if template else (),
    )


def make_provider(name: str):
    if name == "fake":
        from tests.conftest import FakeAssessmentProvider

        return FakeAssessmentProvider()
    from app.config import DEFAULT_DATABASE_URL
    from app.database import create_database
    from app.model_settings import load_model_settings
    from app.providers import SiliconFlowAssessmentProvider

    _, factory = create_database(DEFAULT_DATABASE_URL)
    with factory() as db:
        settings = load_model_settings(db)
    return SiliconFlowAssessmentProvider(
        api_key=settings.api_key,
        model=settings.assessment_model,
        base_url=settings.base_url,
        timeout_seconds=settings.timeout_seconds,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="金标集评分校准")
    parser.add_argument("--provider", choices=["siliconflow", "fake"], default="siliconflow")
    parser.add_argument(
        "--golden",
        default=str(BASE / "backend" / "tests" / "golden" / "answers.jsonl"),
    )
    args = parser.parse_args()

    from app.providers import AssessmentProviderError, BatchAssessmentCase

    rows = load_golden(Path(args.golden))
    provider = make_provider(args.provider)
    cases = []
    for index, row in enumerate(rows):
        cases.append(
            BatchAssessmentCase(
                answer_id=f"golden-{index}",
                question_id=f"golden-{index}",
                question=build_spec(row),
                answer_text=row["answer"],
                case_ref=f"c{index + 1}",
            )
        )

    errors: dict[str, list[float]] = {}
    details: list[tuple[str, int, int | None, str]] = []
    failed_chunks = 0
    for start in range(0, len(cases), 3):
        chunk = cases[start : start + 3]
        try:
            items = provider.assess_batch(chunk)
        except (AssessmentProviderError, AssessmentResponseError) as exc:
            # 单批失败只跳过该批，校准工具要有鲁棒性
            failed_chunks += 1
            print(f"跳过一批（{exc}）", file=sys.stderr)
            continue
        by_id = {item.answer_id: item for item in items}
        for case in chunk:
            row = rows[int(case.answer_id.split("-")[1])]
            item = by_id.get(case.answer_id)
            predicted = item.result.level if item else None
            gap = abs(predicted - row["expected_level"]) if predicted is not None else None
            errors.setdefault(row["knowledge_point_id"], []).append(
                gap if gap is not None else 4.0
            )
            details.append(
                (row["knowledge_point_id"], row["expected_level"], predicted, item.commentary or "")
            )

    if failed_chunks:
        print(f"警告：{failed_chunks} 批评分失败被跳过")
    print(f"金标集 {len(rows)} 条 · 评分器 {getattr(provider, 'prompt_version', 'unknown')}")
    all_errors = []
    for knowledge_point_id, values in sorted(errors.items()):
        mae = statistics.mean(values)
        all_errors.extend(values)
        print(f"  {knowledge_point_id:<36} MAE {mae:.2f}  (n={len(values)})")
    print(f"总体 MAE {statistics.mean(all_errors):.2f}")
    print("\n明细（知识点 / 期望 / 预测 / 模型点评）：")
    for knowledge_point_id, expected, predicted, commentary in details:
        print(f"  {knowledge_point_id:<36} 期望 {expected} → 预测 {predicted}  {commentary[:40]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
