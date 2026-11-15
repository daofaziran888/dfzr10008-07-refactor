"""API接口生成接口：维护接口配置，覆盖发布接口、废弃接口、删除接口等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.apigen import ApigenService
from app.services.frozen import FrozenReferenceError, frozen_version_payload

router = APIRouter(prefix="/api/apigen", tags=["API接口生成"])

service = ApigenService()

LIST_FIELDS = ["接口编号", "接口名称", "请求方法", "请求路径", "参数定义", "响应模板", "超时秒数", "接口状态"]
STATUSES = ["草稿", "测试中", "已发布", "已废弃"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按接口编号检索"),
    status: str | None = Query(default=None, description="草稿、测试中、已发布、已废弃"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按接口编号与状态过滤API接口生成列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/frozen/{version_id}")
def get_frozen_version(version_id: str) -> dict[str, Any]:
    """按冻结版本号查看原聚合口径：历史快照只读，后续编辑不会改写它。"""
    snapshot = frozen_version_payload(version_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"冻结版本 {version_id} 不存在或已归档")
    return snapshot


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出API接口生成清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "apigen", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条接口配置明细；引用冻结版本时返回该版本的字段映射与聚合口径。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"接口配置 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条接口配置，缺字段时说明原因而不是静默丢弃。"""
    try:
        entry, missing = service.create_entry(payload.values)
    except FrozenReferenceError as error:
        return ActionResult(ok=False, message=str(error))
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="接口配置已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条接口配置执行发布接口、废弃接口、删除接口；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """编辑接口配置：可以重新指定引用的冻结版本，聚合口径始终按快照读取。"""
    try:
        entry = service.update_entry(entry_id, payload.values)
    except FrozenReferenceError as error:
        return ActionResult(ok=False, message=str(error))
    if entry is None:
        return ActionResult(ok=False, message=f"接口配置 {entry_id} 不存在或已归档")
    return ActionResult(ok=True, message="接口配置已更新", entry=entry)
