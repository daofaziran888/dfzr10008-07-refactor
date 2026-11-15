"""发布快照的共用冻结逻辑：冻结只写一次，读取只走这里。

模型封装（datapack）一旦发布，字段映射、聚合规则等结果就属于历史发布内容：

- 写入侧只允许新增冻结版本，旧版本快照不可覆盖、不可回写；
- 读取侧统一调用 ``read_entry_view``：模型封装详情、接口配置与数据产品定义
  读到的是同一份快照，不会各自从可编辑字段里再拼一遍。

下游（接口配置、数据产品定义）只保存 ``冻结版本编号`` 这个引用，不复制聚合口径。
"""
from __future__ import annotations

from typing import Any

from app.store import store

# 记录上的引用字段：指向 store 里的冻结版本。
VERSION_FIELD = "冻结版本编号"
# 对外返回时挂载的只读快照对象；详情与下游读取共用同一个结构。
SNAPSHOT_FIELD = "冻结版本快照"
# 参与冻结的字段：字段映射与聚合口径是发布结果的核心，输出结构与缓存策略一并固化。
SNAPSHOT_FIELDS = ("字段映射", "聚合规则", "输出结构", "缓存策略")
# 允许冻结结果取自哪个模块。冻结版本只由模型封装发布产生。
FROZEN_MODULE = "datapack"
# 各模块用于生成版本号前缀的编号字段。
CODE_FIELDS = {
    "datapack": "封装编号",
    "apigen": "接口编号",
    "product": "产品编号",
}
# 这些字段由流程维护，编辑时不能由调用方直接改写。
PROTECTED_FIELDS = {"id", "status", "pending", "abnormal", VERSION_FIELD, SNAPSHOT_FIELD}


class FrozenReferenceError(ValueError):
    """下游提交了不存在或不归属模型封装的冻结版本引用。"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def snapshot_fields(source: dict[str, Any]) -> dict[str, Any]:
    """从来源记录里摘出需要冻结的字段，只认固定字段清单。"""
    return {field: source.get(field) for field in SNAPSHOT_FIELDS}


def next_version_id(entry: dict[str, Any], module: str = FROZEN_MODULE) -> str:
    """按编号顺延生成版本号，例如 DATA-0003 的下一版是 DATA-0003-V2。"""
    code = entry.get(CODE_FIELDS.get(module, "")) or f"{module}-{entry.get('id', 0)}"
    prefix = f"{code}-V"
    sequence = 0
    for version_id in store.frozen_version_ids():
        if version_id.startswith(prefix) and version_id[len(prefix):].isdigit():
            sequence = max(sequence, int(version_id[len(prefix):]))
    return f"{prefix}{sequence + 1}"


def build_version_record(
    module: str,
    entry: dict[str, Any],
    *,
    version_id: str,
    source_status: str | None = None,
) -> dict[str, Any]:
    """把一条发布记录的当前结果固化成冻结版本记录（纯构造，不落库）。"""
    return {
        "version_id": version_id,
        "source_module": module,
        "source_entry_id": int(entry.get("id", 0)),
        "source_code": entry.get(CODE_FIELDS.get(module, "")),
        "source_status": source_status or entry.get("status"),
        "readonly": True,
        **snapshot_fields(entry),
    }


def register_version(record: dict[str, Any]) -> dict[str, Any]:
    """唯一的冻结写入入口：只新增、不覆盖。"""
    store.add_frozen_version(record)
    return record


def read_version(version_id: str | None) -> dict[str, Any] | None:
    """读取一份冻结版本。

    这是全项目唯一的快照读取实现。store 返回深拷贝，调用方改不到历史快照。
    """
    if not version_id:
        return None
    return store.frozen_version(str(version_id))


def read_entry_view(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    """统一的详情读取：记录带冻结引用时，用快照覆盖可变字段。

    返回新字典，不回写仓库。模型封装、接口配置、数据产品定义都走这一个入口，
    因此同一版本号读出的字段映射与聚合口径必然一致。
    """
    if entry is None:
        return None
    view = dict(entry)
    snapshot = read_version(entry.get(VERSION_FIELD))
    if snapshot is None:
        return view
    for field in SNAPSHOT_FIELDS:
        if field in snapshot:
            view[field] = snapshot[field]
    view[VERSION_FIELD] = snapshot["version_id"]
    view[SNAPSHOT_FIELD] = snapshot
    return view


def read_entry_views(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """列表读取：逐条走同一份读取实现，保持原有行序。"""
    return [read_entry_view(entry) for entry in entries]


def freeze_entry(
    module: str,
    entry: dict[str, Any],
    *,
    version_id: str | None = None,
    source_status: str | None = None,
) -> dict[str, Any]:
    """为一条发布记录生成冻结版本，并把引用写回该记录。

    记录已有冻结引用时直接返回原版本，避免重复动作覆盖历史快照。
    """
    existing = read_version(entry.get(VERSION_FIELD))
    if existing is not None:
        return existing
    record = build_version_record(
        module,
        entry,
        version_id=version_id or next_version_id(entry, module),
        source_status=source_status,
    )
    register_version(record)
    entry[VERSION_FIELD] = record["version_id"]
    return record


def freeze_reference_error(values: dict[str, Any]) -> str | None:
    """校验下游提交的冻结版本引用；未传引用视为未关联，返回 None。"""
    version_id = str(values.get(VERSION_FIELD) or "").strip()
    if not version_id:
        return None
    record = read_version(version_id)
    if record is None:
        return f"冻结版本 {version_id} 不存在或已归档"
    if record.get("source_module") != FROZEN_MODULE:
        return f"冻结版本 {version_id} 不属于模型封装，不能作为下游引用"
    return None


def frozen_version_payload(version_id: str) -> dict[str, Any] | None:
    """下游按版本号查看原聚合口径时使用；返回只读快照副本。"""
    return read_version(version_id)


def update_entry_view(entry: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """草稿原地编辑：只接受非流程字段，结果按统一读取实现返回。"""
    for field, value in values.items():
        if field not in PROTECTED_FIELDS:
            entry[field] = value
    return read_entry_view(entry) or {}


def update_reference_entry(entry: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """下游记录的原地编辑：只改自身字段，可重新指向另一份冻结版本。

    冻结字段（字段映射、聚合规则等）不接受下游写入，读取时一律以冻结版本为准。
    """
    reference_error = freeze_reference_error(values)
    if reference_error:
        raise FrozenReferenceError(reference_error)
    if VERSION_FIELD in values:
        version_id = str(values.get(VERSION_FIELD) or "").strip()
        if version_id:
            entry[VERSION_FIELD] = version_id
        else:
            entry.pop(VERSION_FIELD, None)
    for field, value in values.items():
        if field in PROTECTED_FIELDS or field in SNAPSHOT_FIELDS:
            continue
        entry[field] = value
    return read_entry_view(entry) or {}
