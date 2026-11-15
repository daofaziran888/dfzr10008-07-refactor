"""冻结版本回归测试：发布结果只读、编辑生成新版本、下游按冻结版本读取。

运行：cd backend && .venv/bin/python -m unittest discover -s tests
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.frozen import frozen_version_payload  # noqa: E402
from app.store import store  # noqa: E402


class FrozenVersionTest(unittest.TestCase):
    def setUp(self) -> None:
        store.reset()
        self.client = TestClient(app)

    def test_published_detail_matches_downstream_reference(self) -> None:
        """DATA-0003 详情、APIG-0003 接口配置读到同一份字段映射与聚合口径。"""
        packaging = self.client.get('/api/datapack/3').json()
        api = self.client.get('/api/apigen/3').json()
        product = self.client.get('/api/product/3').json()

        self.assertEqual(packaging['封装编号'], 'DATA-0003')
        self.assertEqual(packaging['status'], '已发布')
        self.assertEqual(packaging['字段映射'], 'order_id、amount、store_id')
        self.assertEqual(packaging['聚合规则'], '按门店日汇总')
        for entry in (packaging, api, product):
            self.assertEqual(entry['字段映射'], 'order_id、amount、store_id')
            self.assertEqual(entry['聚合规则'], '按门店日汇总')
            self.assertEqual(entry['冻结版本编号'], 'DATA-0003-V1')

    def test_edit_published_only_creates_new_version(self) -> None:
        """把 DATA-0003 改为按渠道汇总只生成新版本，旧接口仍读原聚合口径。"""
        revised = self.client.put(
            '/api/datapack/3', json={'values': {'聚合规则': '按渠道汇总'}}
        ).json()

        self.assertTrue(revised['ok'])
        new_entry = revised['entry']
        self.assertEqual(new_entry['id'], 4)
        self.assertEqual(new_entry['聚合规则'], '按渠道汇总')
        self.assertNotEqual(new_entry['status'], '已发布')
        self.assertNotIn('冻结版本编号', new_entry)

        # 旧的已发布封装与下游引用保持不变
        old = self.client.get('/api/datapack/3').json()
        self.assertEqual(old['聚合规则'], '按门店日汇总')
        self.assertEqual(old['字段映射'], 'order_id、amount、store_id')
        self.assertEqual(old['status'], '已发布')
        self.assertEqual(old['冻结版本编号'], 'DATA-0003-V1')
        self.assertEqual(self.client.get('/api/apigen/3').json()['聚合规则'], '按门店日汇总')
        self.assertEqual(self.client.get('/api/product/3').json()['聚合规则'], '按门店日汇总')

    def test_new_version_freezes_on_publish(self) -> None:
        """新版本发布后生成独立冻结版本，旧快照仍可查看。"""
        revised = self.client.put(
            '/api/datapack/3', json={'values': {'聚合规则': '按渠道汇总'}}
        ).json()
        new_id = revised['entry']['id']

        published = self.client.post(
            f'/api/datapack/{new_id}/actions', json={'values': {'action': '发布封装'}}
        ).json()
        self.assertTrue(published['ok'])

        self.assertEqual(
            self.client.get('/api/datapack/frozen/DATA-0003-V1').json()['聚合规则'],
            '按门店日汇总',
        )
        self.assertEqual(
            self.client.get('/api/datapack/frozen/DATA-0003-V2').json()['聚合规则'],
            '按渠道汇总',
        )
        self.assertEqual(
            frozen_version_payload('DATA-0003-V1')['字段映射'],
            'order_id、amount、store_id',
        )

    def test_snapshot_is_read_only(self) -> None:
        """改不动历史快照：返回的是副本，重复发布也不会覆盖。"""
        snapshot = frozen_version_payload('DATA-0003-V1')
        snapshot['聚合规则'] = '被改坏的口径'
        self.assertEqual(frozen_version_payload('DATA-0003-V1')['聚合规则'], '按门店日汇总')

        raw = store.find('datapack', 3)
        raw['聚合规则'] = '被改坏的口径'
        self.assertEqual(
            self.client.get('/api/datapack/3').json()['聚合规则'],
            '按门店日汇总',
        )

    def test_downstream_rejects_unknown_reference(self) -> None:
        """下游引用不存在的冻结版本会被拦下，不静默写入。"""
        result = self.client.post(
            '/api/apigen',
            json={
                'values': {
                    '接口编号': 'APIG-9001',
                    '接口名称': '过期引用样例',
                    '请求方法': 'GET',
                    '冻结版本编号': 'DATA-9999-V9',
                }
            },
        ).json()
        self.assertFalse(result['ok'])
        self.assertIn('DATA-9999-V9', result['message'])

    def test_list_order_and_status_preserved(self) -> None:
        """原有展示顺序与封装状态不变。"""
        rows = self.client.get('/api/datapack').json()['items']
        self.assertEqual([row['id'] for row in rows], [1, 2, 3])
        self.assertEqual([row['status'] for row in rows], ['草稿', '已封装', '已发布'])


if __name__ == '__main__':
    unittest.main()
