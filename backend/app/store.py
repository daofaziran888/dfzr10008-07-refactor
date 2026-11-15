"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。

冻结版本单独放一张只读表：发布快照只有一份，读取一律返回深拷贝，调用方改不到仓库里的内容。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.seed import SEED_FROZEN_VERSIONS, SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {}
        # 冻结版本只增不改：快照一旦写入就不再回写，读出去的是副本。
        self._frozen: dict[str, dict[str, Any]] = {}
        self.reset()

    def reset(self) -> None:
        """把仓库恢复成示例数据初始状态，便于测试与本地重置。"""
        self._tables = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self._frozen = deepcopy(SEED_FROZEN_VERSIONS)

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def frozen_version(self, version_id: str) -> dict[str, Any] | None:
        """按版本号读取冻结版本；返回深拷贝，外部拿到的对象和仓库里的快照互不影响。"""
        record = self._frozen.get(version_id)
        return deepcopy(record) if record is not None else None

    def add_frozen_version(self, record: dict[str, Any]) -> None:
        """登记一份新的冻结版本；同一个版本号不允许覆盖写入。"""
        version_id = str(record.get("version_id") or "").strip()
        if not version_id:
            raise ValueError("冻结版本缺少 version_id")
        if version_id in self._frozen:
            raise ValueError(f"冻结版本 {version_id} 已存在，发布快照不能覆盖")
        self._frozen[version_id] = deepcopy(record)

    def frozen_version_ids(self) -> list[str]:
        return sorted(self._frozen)

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
