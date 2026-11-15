"""数据模型封装业务规则：状态流转、字段校验与筛选口径都收在这里。

发布后的字段映射与聚合口径由冻结版本承载：详情读取统一走 `frozen.read_entry_view`，
后续编辑只新增版本，不会改写已发布内容。
"""
from __future__ import annotations

from typing import Any

from app.services.frozen import (
    PROTECTED_FIELDS,
    SNAPSHOT_FIELDS,
    VERSION_FIELD,
    freeze_entry,
    read_entry_view,
    read_entry_views,
    update_entry_view,
)
from app.store import store

MODULE = "datapack"
REQUIRED_FIELDS = ["封装编号", "封装名称", "原始数据源"]
STATUS_ORDER = ["草稿", "已封装", "已发布", "已废弃"]
# 状态流转保持原有口径不变；发布封装是触发冻结的动作。
ACTION_RULES = {"发布封装": "草稿", "废弃封装": "已封装", "删除封装": "已发布"}
NEGATIVE_ACTIONS = []
PUBLISH_ACTION = "发布封装"


class DatapackService:
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
            rows = [row for row in rows if keyword in str(row.get("封装编号", ""))]
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
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry.update({field: values.get(field) for field in SNAPSHOT_FIELDS if field in values})
        rows.append(entry)
        return read_entry_view(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"模型封装 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据模型封装可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if action == PUBLISH_ACTION:
            # 发布即冻结当时的字段映射与聚合口径；已有快照不会被重复发布覆盖。
            freeze_entry(MODULE, entry)
        return read_entry_view(entry), f"模型封装已{action}"

    def revise_entry(self, entry_id: int, values: dict[str, Any]) -> dict[str, Any] | None:
        """编辑模型封装：不改旧版本，另起一条草稿承载新改动。

        旧记录连同它的冻结版本保持原样，下游仍按原聚合口径读取；新改动要等
        新版本发布后才会生成新的冻结版本。
        """
        source = store.find(MODULE, entry_id)
        if source is None:
            return None
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field, value in source.items():
            if field not in PROTECTED_FIELDS:
                entry[field] = value
        for field, value in values.items():
            if field not in PROTECTED_FIELDS:
                entry[field] = value
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return read_entry_view(entry)

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> dict[str, Any] | None:
        """统一的编辑入口：已发布记录只生成新版本，草稿才原地修改。"""
        source = store.find(MODULE, entry_id)
        if source is None:
            return None
        if source.get(VERSION_FIELD):
            return self.revise_entry(entry_id, values)
        return update_entry_view(source, values)
