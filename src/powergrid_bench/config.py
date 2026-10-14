"""Explicit configuration catalog; null is never an executable default."""

from __future__ import annotations

import copy
import math
import re
from dataclasses import asdict, dataclass
from typing import Any

TASKS = (
    "goc-sc-ac-opf",
    "unit-commitment",
    "rte-maintenance",
    "l2rpn-grid-control",
    "heftcom-forecast-trade",
)


@dataclass(frozen=True)
class FieldSpec:
    path: str
    kind: str
    description: str
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    model_only: bool = False


FIELDS = (
    FieldSpec("identity.run_id", "string", "独立运行标识"),
    FieldSpec("identity.cohort_id", "string", "同预算与恢复规则的比较组"),
    FieldSpec("identity.task_id", "string", "任务家族", TASKS),
    FieldSpec("identity.task_release_sha256", "digest", "认证任务 release 的内容摘要"),
    FieldSpec("identity.protocol_id", "string", "研究协议与版本"),
    FieldSpec("identity.split_sha256", "digest", "数据角色／计分面板承诺摘要"),
    FieldSpec("identity.evaluator_sha256", "digest", "可信评分实现摘要"),
    FieldSpec(
        "ranking.kind",
        "string",
        "结果结论范围",
        ("new-benchmark", "historical-reference", "agent-generalization"),
    ),
    FieldSpec("ranking.capability_profile", "string", "所有方法共同的动作／工具权限"),
    FieldSpec("ranking.aggregation_id", "string", "任务内聚合与归一化版本"),
    FieldSpec(
        "method.backend",
        "string",
        "开发／搜索方法",
        ("coding-agent", "population-evolution", "training", "solver-reference"),
    ),
    FieldSpec("method.version_sha256", "digest", "方法／agent 实现摘要"),
    FieldSpec("method.initial_artifact_sha256", "digest", "共同初始算法／回退候选"),
    FieldSpec("method.context_policy", "string", "初始上下文、记忆、工具与外部信息权限"),
    FieldSpec("model.identifier", "string", "模型标识或固定 profile", model_only=True),
    FieldSpec(
        "model.single_response_max_tokens", "integer", "单次响应上限", minimum=1, model_only=True
    ),
    FieldSpec("model.context_policy", "string", "上下文窗口与压缩政策", model_only=True),
    FieldSpec("model.retry_policy_id", "string", "有限重试、流式响应恢复政策", model_only=True),
    FieldSpec(
        "budgets.development_seconds", "number", "准备完成后的总开发墙钟 T", minimum=0.000001
    ),
    FieldSpec("budgets.feedback_jobs", "integer", "最多受理作业 n；0 明确零反馈", minimum=0),
    FieldSpec("budgets.feedback_timeout_seconds", "number", "单次反馈执行时限", minimum=0.000001),
    FieldSpec("budgets.build_timeout_seconds", "number", "最终构建／编译时限", minimum=0.000001),
    FieldSpec(
        "budgets.final_case_timeout_seconds", "number", "每实例／episode 执行时限", minimum=0.000001
    ),
    FieldSpec(
        "budgets.final_batch_timeout_seconds", "number", "完整最终面板总时限", minimum=0.000001
    ),
    *(
        FieldSpec(f"resources.{phase}.{name}", "number", f"{phase} 的 {label}", minimum=minimum)
        for phase in ("development", "feedback", "final")
        for name, label, minimum in (
            ("cpus", "CPU 配额", 0.000001),
            ("memory_mb", "内存", 1),
            ("storage_mb", "临时磁盘", 1),
            ("gpus", "GPU 配额；0 为不使用", 0),
        )
    ),
    FieldSpec("selection.metric_direction", "string", "公开选择指标方向", ("higher", "lower")),
    FieldSpec("selection.feedback_schema_id", "string", "允许反馈的聚合、诊断与截断版本"),
    FieldSpec("recovery.policy_id", "string", "同作业重试／整个开发重跑的政策版本"),
    FieldSpec("recovery.max_infrastructure_attempts", "integer", "同快照执行的有限次数", minimum=1),
    FieldSpec("artifacts.max_files", "integer", "算法包文件数量上限", minimum=1),
    FieldSpec("artifacts.max_bytes", "integer", "算法包字节上限", minimum=1),
    FieldSpec("repetitions.count", "integer", "独立开发重复数", minimum=1),
    FieldSpec("repetitions.development_seeds", "array", "配对、不同的开发 seed"),
    FieldSpec("evaluation.seeds", "array", "最终面板预注册的评测 seed"),
    FieldSpec("evaluation.tolerance_policy_id", "string", "数值容差／随机性重放准则"),
    FieldSpec("deployment.backend_profile", "string", "本机／Harbor／集群环境版本"),
    FieldSpec("deployment.runtime_image_digest", "string", "执行镜像不可变 sha256 digest"),
    FieldSpec("deployment.certification_sha256", "digest", "真实 backend 验收记录摘要"),
)

POLICY = {
    "cumulative_token_cap": None,
    "token_reservation": False,
    "feedback_zero_means": "no-protected-feedback",
    "selection": "best-public-selection",
    "tie_break": "earliest-completed",
    "final_test_selects_candidates": False,
}


def template_configuration() -> dict:
    """Return an undecided template, preserving already agreed protocol policies."""
    result: dict[str, Any] = {"schema_version": "1.0", "status": "draft"}
    for field in FIELDS:
        parent = result
        parts = field.path.split(".")
        for part in parts[:-1]:
            parent = parent.setdefault(part, {})
        parent[parts[-1]] = None
    result["policy"] = copy.deepcopy(POLICY)
    return result


@dataclass(frozen=True)
class ValidationReport:
    valid_draft: bool
    executable: bool
    unresolved: tuple[str, ...]
    errors: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _value(config: dict, path: str) -> Any:
    value: Any = config
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _unknown(actual: Any, expected: dict, prefix: str = "") -> list[str]:
    if not isinstance(actual, dict):
        return [f"{prefix or 'configuration'} must be an object"]
    errors = []
    for key, value in actual.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in expected:
            errors.append(f"unknown field: {path}")
        elif isinstance(expected[key], dict):
            errors.extend(_unknown(value, expected[key], path))
    return errors


def validate_configuration(config: dict) -> ValidationReport:
    """Validate structure/completeness; backend/task certification is a separate gate."""
    expected = template_configuration()
    errors = _unknown(config, expected)
    if not isinstance(config, dict):
        return ValidationReport(False, False, (), tuple(errors))
    if config.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    if config.get("status") not in ("draft", "configured"):
        errors.append("status must be draft or configured")
    policy = config.get("policy")
    if (
        policy != POLICY
        or not isinstance(policy, dict)
        or any(type(policy.get(key)) is not type(value) for key, value in POLICY.items())
    ):
        errors.append("policy must preserve the agreed no-cap, zero-feedback and selection rules")
    unresolved = []
    model_needed = _value(config, "method.backend") in (
        "coding-agent",
        "population-evolution",
        None,
    )
    for field in FIELDS:
        value = _value(config, field.path)
        if field.model_only and not model_needed:
            if value is not None:
                errors.append(f"{field.path} must be null for a non-model backend")
            continue
        if value is None:
            unresolved.append(field.path)
            continue
        try:
            numeric = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            numeric = False
        valid = {
            "string": isinstance(value, str) and bool(value.strip()),
            "digest": isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value)),
            "integer": type(value) is int,
            "number": numeric,
            "array": isinstance(value, list)
            and bool(value)
            and all(type(item) is int and item >= 0 for item in value),
            "boolean": type(value) is bool,
        }[field.kind]
        if not valid:
            errors.append(f"{field.path}: expected {field.kind}")
        elif field.choices and value not in field.choices:
            errors.append(f"{field.path}: choose from {field.choices}")
        elif field.minimum is not None and value < field.minimum:
            errors.append(f"{field.path}: minimum is {field.minimum}")
    count = _value(config, "repetitions.count")
    seeds = _value(config, "repetitions.development_seeds")
    if type(count) is int and isinstance(seeds, list):
        if len(seeds) != count or len(set(map(repr, seeds))) != len(seeds):
            errors.append("repetitions require exactly count distinct paired development seeds")
    image = _value(config, "deployment.runtime_image_digest")
    if image is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", str(image)):
        errors.append("deployment.runtime_image_digest must be immutable sha256:<64 hex>")
    valid = not errors
    return ValidationReport(
        valid,
        valid and not unresolved and config.get("status") == "configured",
        tuple(unresolved),
        tuple(errors),
    )


def configuration_catalog() -> dict:
    return {
        "schema_version": "1.0",
        "status": "design",
        "values_are_undecided": True,
        "fields": [asdict(field) for field in FIELDS],
        "agreed_protocol_policy": POLICY,
        "completeness_is_not_task_or_backend_certification": True,
    }
