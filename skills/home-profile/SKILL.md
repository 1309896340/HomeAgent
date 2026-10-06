---
name: home-profile
description: 家庭档案：家中已接入的智能设备清单、房间布局与成员偏好。任何涉及家中设备、传感器、家电状态或家居控制的问题，都应先阅读本技能再回答或调用工具。
---

# 家庭档案（测试数据）

> 注意：当前数据来自 mock 服务，仅供联调测试；家中实际硬件尚未接入。

## 设备清单

| device_id | 名称 | 类型 | 能力 |
|---|---|---|---|
| living-light | 客厅主灯 | light | on / off |
| temp-living | 客厅温湿度传感器 | sensor | 温度、湿度只读 |
| door-lock | 入户门锁 | lock | lock / unlock |
| air-purifier | 空气净化器 | appliance | mode: auto/sleep/off |

## 工具使用规则

- 查询所有设备概览 → `list_devices()`
- 查询单台设备实时状态 → `get_device_status(device_id)`
- 控制设备 → `control_device(device_id, action)`，action 取值见上表
- **传感器实时数值必须以工具返回为准，禁止凭记忆或想象回答**
- 用户要求控制清单中不存在的设备时，如实说明没有该设备，不要虚构执行结果

## 成员与作息（占位）

- 家庭成员：wind
- 起床 07:30，睡眠 23:30
