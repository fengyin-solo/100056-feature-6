"""检修任务业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "task"
REQUIRED_FIELDS = ["任务编号", "关联计划", "检修人员"]
STATUS_ORDER = ["待开始", "检修中", "待验收", "已完成"]
ACTION_RULES = {"开始任务": "检修中", "提交验收": "待验收", "确认完成": "已完成"}
NEGATIVE_ACTIONS = []
DONE_STATUS = STATUS_ORDER[-1]


def _to_int(value: Any) -> int | None:
    """把遗留问题数、检修项目数这类计数字段转成整数；转不动就返回 None。"""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def is_flagged(entry: dict[str, Any]) -> bool:
    """遗留问题数超过检修项目数的任务要单独标出来。"""
    leftover = _to_int(entry.get("遗留问题数"))
    items = _to_int(entry.get("检修项目数"))
    return leftover is not None and items is not None and leftover > items


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

    def stats(self) -> list[dict[str, Any]]:
        """列表上方的统计卡：待开始、检修中按条数计，遗留问题按问题数合计。"""
        rows = store.rows(MODULE)
        leftover_total = sum(
            value for row in rows if (value := _to_int(row.get("遗留问题数"))) is not None
        )
        return [
            {"label": "待开始任务", "value": sum(1 for row in rows if row.get("status") == "待开始")},
            {"label": "检修中任务", "value": sum(1 for row in rows if row.get("status") == "检修中")},
            {"label": "遗留问题合计", "value": leftover_total},
        ]

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["任务状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
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
        """把一批检修任务转派给同一批检修人员，逐条返回结果。

        校验不通过（任务不存在、已确认完成、人员未变）或执行失败的任务都留在原状态；
        遗留问题数超过检修项目数的任务在结果里单独标记，不影响转派本身。
        """
        assignee = assignee.strip()
        if not ids:
            return self._batch_result(False, "未选择需要转派的检修任务", [])
        if not assignee:
            return self._batch_result(False, "转派后的检修人员不能为空", [])

        items: list[dict[str, Any]] = []
        for task_id in ids:
            entry = store.find(MODULE, task_id)
            if entry is None:
                items.append(self._batch_item(task_id, "", False, False,
                                              f"检修任务 {task_id} 不存在或已归档", None))
                continue
            code = str(entry.get("任务编号") or f"TASK-{task_id}")
            flagged = is_flagged(entry)
            if entry.get("status") == DONE_STATUS:
                items.append(self._batch_item(task_id, code, False, flagged,
                                              "任务已确认完成，不能再次转派", None))
                continue
            if str(entry.get("检修人员") or "").strip() == assignee:
                items.append(self._batch_item(task_id, code, False, flagged,
                                              f"检修人员已经是{assignee}，无需转派", None))
                continue
            try:
                target = store.find(MODULE, task_id)
                if target is None:
                    raise LookupError(f"检修任务 {task_id} 写入前已不存在")
                target["检修人员"] = assignee
            except Exception:  # 执行失败：不落任何改动，任务留在原状态
                items.append(self._batch_item(task_id, code, False, flagged,
                                              "转派执行失败，任务保留原状态", None))
                continue
            items.append(self._batch_item(task_id, code, True, flagged,
                                          f"已转派给{assignee}", dict(target)))

        succeeded = sum(1 for item in items if item["ok"])
        failed = len(items) - succeeded
        flagged_count = sum(1 for item in items if item["flagged"])
        message = f"批量转派完成：成功 {succeeded} 条，失败 {failed} 条，遗留超标 {flagged_count} 条"
        return self._batch_result(failed == 0, message, items)

    @staticmethod
    def _batch_item(
        task_id: int,
        code: str,
        ok: bool,
        flagged: bool,
        message: str,
        entry: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "id": task_id,
            "code": code,
            "ok": ok,
            "flagged": flagged,
            "message": message,
            "entry": entry,
        }

    @staticmethod
    def _batch_result(ok: bool, message: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "ok": ok,
            "message": message,
            "total": len(items),
            "succeeded": sum(1 for item in items if item["ok"]),
            "failed": sum(1 for item in items if not item["ok"]),
            "flagged": sum(1 for item in items if item["flagged"]),
            "results": items,
        }
