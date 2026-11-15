"""数据模型封装接口：维护模型封装，覆盖发布封装、废弃封装、删除封装等动作。

发布结果是唯一冻结来源：已发布记录只读，编辑生成新版本，历史快照按
`冻结版本编号` 引用。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.datapack import DatapackService
from app.services.frozen import frozen_version_payload

router = APIRouter(prefix="/api/datapack", tags=["数据模型封装"])

service = DatapackService()

LIST_FIELDS = ["封装编号", "封装名称", "原始数据源", "输出结构", "字段映射", "聚合规则", "缓存策略", "封装状态"]
STATUSES = ["草稿", "已封装", "已发布", "已废弃"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按封装编号检索"),
    status: str | None = Query(default=None, description="草稿、已封装、已发布、已废弃"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按封装编号与状态过滤数据模型封装列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/frozen/{version_id}")
def get_frozen_version(version_id: str) -> dict[str, Any]:
    """按冻结版本号读取历史发布结果；字段映射与聚合口径保持只读。"""
    snapshot = frozen_version_payload(version_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"冻结版本 {version_id} 不存在或已归档")
    return snapshot


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出数据模型封装清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "datapack", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条模型封装明细；已发布记录返回冻结版本里的字段映射与聚合口径。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"模型封装 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条模型封装，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="模型封装已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条模型封装执行发布封装、废弃封装、删除封装；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/revisions", response_model=ActionResult)
def revise_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """编辑模型封装：已发布记录只会生成新版本，历史快照与聚合口径保持只读。"""
    entry = service.update_entry(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=f"模型封装 {entry_id} 不存在或已归档")
    return ActionResult(ok=True, message="模型封装已生成新版本", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """编辑模型封装字段映射：已发布记录按新改动生成新版本，不覆盖历史发布结果。"""
    entry = service.update_entry(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=f"模型封装 {entry_id} 不存在或已归档")
    return ActionResult(ok=True, message="模型封装已更新", entry=entry)
