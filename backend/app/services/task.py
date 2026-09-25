"""检修任务业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "task"
REQUIRED_FIELDS = ["任务编号", "关联计划", "检修人员"]
OPTIONAL_FIELDS = ["开始时间", "完成时间", "检修项目数", "遗留问题数"]
STATUS_ORDER = ["待开始", "检修中", "待验收", "已完成"]
ACTION_RULES = {"开始任务": "检修中", "提交验收": "待验收", "确认完成": "已完成"}
NEGATIVE_ACTIONS = []
# 批量转派成功后任务回到检修中，由新检修人员继续处理遗留问题。
REASSIGN_TARGET_STATUS = "检修中"


def to_int(value: Any) -> int:
    """把遗留问题数、检修项目数这类字段安全地转成整数，脏数据按 0 计。"""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def is_overloaded(entry: dict[str, Any]) -> bool:
    """遗留问题数超过检修项目数的任务需要单独标出。"""
    return to_int(entry.get("遗留问题数")) > to_int(entry.get("检修项目数"))


def leftover_total() -> int:
    """全部检修任务的遗留问题合计，供任务列表与值班交接等入口共用。"""
    return sum(to_int(row.get("遗留问题数")) for row in store.rows(MODULE))


class TaskService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def summary(self) -> dict[str, int]:
        """列表上方的统计卡片：状态计数、遗留问题合计与遗留超标任务数。"""
        rows = store.rows(MODULE)
        return {
            "待开始任务": sum(1 for row in rows if row.get("status") == "待开始"),
            "检修中任务": sum(1 for row in rows if row.get("status") == "检修中"),
            "遗留问题合计": leftover_total(),
            "遗留超标任务": sum(1 for row in rows if is_overloaded(row)),
        }

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in OPTIONAL_FIELDS:
            entry[field] = values.get(field)
        entry["检修项目数"] = to_int(entry.get("检修项目数"))
        entry["遗留问题数"] = to_int(entry.get("遗留问题数"))
        entry["status"] = STATUS_ORDER[0]
        entry["任务状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = is_overloaded(entry)
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"检修任务 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于检修任务可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["任务状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"检修任务已{action}"

    def batch_reassign(self, ids: list[int], assignee: str) -> dict[str, Any]:
        """多选任务按同一批检修人员转派：逐条校验、逐条给结果，失败的留在原状态。"""
        assignee = assignee.strip()
        if not ids:
            return {"ok": False, "message": "未选择需要转派的检修任务", "total": 0,
                    "succeeded": 0, "failed": 0, "flagged": 0, "results": []}
        if not assignee:
            return {"ok": False, "message": "请填写接收任务的检修人员", "total": 0,
                    "succeeded": 0, "failed": 0, "flagged": 0, "results": []}
        results: list[dict[str, Any]] = []
        for entry_id in ids:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                results.append({"id": entry_id, "code": "", "ok": False, "flagged": False,
                                "message": f"检修任务 {entry_id} 不存在或已归档", "entry": None})
                continue
            code = str(entry.get("任务编号") or f"#{entry_id}")
            flagged = is_overloaded(entry)
            if entry.get("status") == STATUS_ORDER[-1]:
                results.append({"id": entry_id, "code": code, "ok": False, "flagged": flagged,
                                "message": f"{code} 已确认完成，不能再次转派", "entry": None})
                continue
            if str(entry.get("检修人员") or "").strip() == assignee:
                results.append({"id": entry_id, "code": code, "ok": False, "flagged": flagged,
                                "message": f"{code} 已在 {assignee} 名下，无需转派", "entry": None})
                continue
            entry["检修人员"] = assignee
            entry["status"] = REASSIGN_TARGET_STATUS
            entry["任务状态"] = REASSIGN_TARGET_STATUS
            entry["pending"] = True
            if flagged:
                entry["abnormal"] = True
            results.append({"id": entry_id, "code": code, "ok": True, "flagged": flagged,
                            "message": f"{code} 已转派给 {assignee}，任务回到{REASSIGN_TARGET_STATUS}",
                            "entry": dict(entry)})
        succeeded = sum(1 for item in results if item["ok"])
        failed = len(results) - succeeded
        flagged_count = sum(1 for item in results if item["flagged"])
        message = f"批量转派完成：共 {len(results)} 条，成功 {succeeded} 条，失败 {failed} 条"
        if flagged_count:
            message += f"，其中遗留超标 {flagged_count} 条"
        return {"ok": True, "message": message, "total": len(results),
                "succeeded": succeeded, "failed": failed, "flagged": flagged_count,
                "results": results}
