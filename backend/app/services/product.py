"""数据产品定义业务规则：状态流转、字段校验与筛选口径都收在这里。

数据产品只保存对模型封装冻结版本的引用（`冻结版本编号`），详情读取统一走
`frozen.read_entry_view`，按冻结版本展示字段映射与聚合口径。
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

MODULE = "product"
REQUIRED_FIELDS = ["产品编号", "产品名称", "产品类型"]
STATUS_ORDER = ["草稿", "开发中", "已发布", "已下线"]
ACTION_RULES = {"发布产品": "草稿", "下线产品": "已发布", "删除产品": "已下线"}
NEGATIVE_ACTIONS = ["下线产品"]


class ProductService:
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
            rows = [row for row in rows if keyword in str(row.get("产品编号", ""))]
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
            # 数据产品定义按冻结版本引用，不复制字段映射与聚合口径。
            entry[VERSION_FIELD] = version_id
        rows.append(entry)
        return read_entry_view(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"数据产品 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据产品定义可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return read_entry_view(entry), f"数据产品已{action}"

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> dict[str, Any] | None:
        """编辑数据产品定义：可重新指定冻结版本，字段映射始终按快照读取。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return update_reference_entry(entry, values)
