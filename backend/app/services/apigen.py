"""API接口生成业务规则：状态流转、字段校验与筛选口径都收在这里。

接口配置只保存对模型封装冻结版本的引用（`冻结版本编号`），字段映射与聚合口径
统一通过 `frozen.read_entry_view` 从冻结版本读取，不再保留聚合规则副本。
"""
from __future__ import annotations

from typing import Any

from app.services.frozen import (
    FrozenReferenceError,
    VERSION_FIELD,
    freeze_reference_error,
    read_entry_view,
    read_entry_views,
    update_reference_entry,
)
from app.store import store

MODULE = "apigen"
REQUIRED_FIELDS = ["接口编号", "接口名称", "请求方法"]
STATUS_ORDER = ["草稿", "测试中", "已发布", "已废弃"]
ACTION_RULES = {"发布接口": "草稿", "废弃接口": "已发布", "删除接口": "已废弃"}
NEGATIVE_ACTIONS = []


class ApigenService:
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
            rows = [row for row in rows if keyword in str(row.get("接口编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return read_entry_views(rows[start:start + size]), total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return read_entry_view(store.find(MODULE, entry_id))

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        reference_error = freeze_reference_error(values)
        if reference_error:
            raise FrozenReferenceError(reference_error)
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        version_id = str(values.get(VERSION_FIELD) or "").strip()
        if version_id:
            # 只存引用，不复制聚合口径：下游读到的始终是冻结版本里的那一份。
            entry[VERSION_FIELD] = version_id
        rows.append(entry)
        return read_entry_view(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"接口配置 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于API接口生成可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return read_entry_view(entry), f"接口配置已{action}"

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> dict[str, Any] | None:
        """编辑接口配置：只改自身字段或重新指定冻结版本，口径仍从快照读取。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return update_reference_entry(entry, values)
