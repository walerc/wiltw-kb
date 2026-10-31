# 宏观环境 · 板块联动追踪方案

> 定稿：2026-11 · 状态：已部署运行
> 目标：宏观环境作为单一事实源，联动金属/涌现/厄尔尼诺等板块，形成「高频数据 + 定期汇总报告」双维度追踪。

---

## 一、追踪架构（两个维度）

```
维度一·高频数据（日度，自动）  →  数据层实时滚动，静默为主，异动才推送
维度二·定期汇总报告（周/月）   →  整合各板块联动结论，人工阅读，辅助决策
```

| 维度 | 频率 | 形态 | 触发 | 交付 |
|---|---|---|---|---|
| 高频数据 | 每日 | 状态机 + 面板 + 扫描盘 | cron（no_agent 脚本） | 异动时推送，无变化静默 |
| 汇总报告 | 每周五 / 每月1号 | 综合报告（中文） | cron（agent 整合解读） | 主动推送汇总 |

---

## 二、联动关系（单一事实源）

**宏观底座 `macro_env.json` 是唯一事实源**，各板块订阅、不再各自拉宏观：

| 板块 | 联动方式 | 订阅内容 |
|---|---|---|
| 涌现 emergence | `emergence_assess.py → load_macro_env()` | 四驱动 + 相变预警（挂 out["macro_env"]） |
| 金属 metal_tracker | `metal_tracker.py → load_macro_env()` + `fetch_macro()` | 康波(第5轮)、regime、drivers、alerts、DXY/CPI 实时 |
| 金属 metal_kondratieff | PHASES 对齐周金涛原著 | 康波时间划分统一（繁荣1991-2004/衰退2004-2015/萧条2015-2025/回升2025-2045） |
| 金属 metal_factor_analysis | ISM 用统一底座拼接 | us_ism_pmi 补 akshare 滞后尾段 |
| 厄尔尼诺 el-nino | `fetch_tracking.py → load_macro_env()` | 宏观环境（短周期顺风/逆风） |

**口径统一**（用户红线：尺度一致性）：
- 康波：第五轮，繁荣1991-2004 / 衰退2004-2015 / 萧条2015-2025 / 回升2025-2045
- 资产定性：黄金=实际利率镜像（非普通商品），现金=货币资产（年化/12）
- 评估尺度：月度景气（当前值+近1月趋势），宏观评估与资产比较同尺度

---

## 三、维度一：高频数据（日度 cron 清单）

| 时间 | cron | 数据流 |
|---|---|---|
| 07:00 | 宏观底座 `macro_update.sh` | fetch 36 指标 → build_macro_env → 部署 macro_env.json |
| 15:35 | 金属突破 `metal_tracker_daily.sh` | 关键位突破提醒（仅突破时推送） |
| 15:40 | 金属面板 `metal_tracker.sh` | 多因子面板 + data.json（读 macro_env 联动） |
| 17:30 | 涌现扫描 `emergence_update.sh` | crowding + fundamental + emergence（读 macro_env 联动） |
| 工作日 | 期货/股指 K线、通道、季节性等 | 各品种技术面 |

高频数据原则：**静默为主**。只有"异动"（突破/相变预警/流动性枯竭触发/观点反转）才推送，避免信息轰炸。

---

## 四、维度二：定期汇总报告（cron 清单）

| 时间 | 报告 | 内容 |
|---|---|---|
| 每周五 16:30 | 观点层更新 `04efe980e7f2` | 券商观点收集，刷新 opinions.json |
| 每周五 17:00 | **宏观环境周报** | macro_env 状态机 + 各板块联动结论 + 相变预警 + 流动性监测 |
| 每月 1 号 09:00 | **宏观环境月报** | 康波 + 库存周期 + 月度景气 + 地区格局 + 观点层共识度 |

### 周报内容规范（每周五 17:00）

读 `macro_env.json` + 各板块输出，生成：

1. **一句话宏观判断**：regime 象限 + 四驱动状态 + 相变预警状态
2. **三尺度定位**：康波（定方向）+ 库存（定节奏）+ 月度景气（定短期）
3. **地区格局**：美/中/欧/日分化 + 全球流动性边际
4. **流动性监测**：SOFR 三件套（距目标上限 / SOFR-EFFR / SOFR-ON RRP）+ 信用/恐慌
5. **板块联动结论**：
   - 金属：康波回升期方向 + 贵金属/工业金属强弱
   - 涌现：本周涌现品种 + 相变信号
   - 拥挤度：家人/外资/机构持仓异动
6. **观点层共识度**：各命题共识/分歧 + 事实 vs 观点偏差
7. **下周关注**：即将公布的宏观数据 + 需盯的临界信号

### 月报内容规范（每月 1 号）

1. **康波定位**：第5轮康波回升期确认度 + 商品长牛证据链
2. **库存周期**：主动补库/被动去库阶段 + PPI 方向
3. **月度景气复盘**：上月四驱动走势 + regime 象限迁移
4. **地区格局**：美中欧日政策分化 + 套息交易状态
5. **观点层月度共识**：券商观点 vs 事实层偏差汇总
6. **下月展望**：关键宏观事件 + 资产配置建议

---

## 五、部署结构

```
~/projects/trading-system/macro_framework/  源码（fetch/build/registry/DESIGN/TRACKING）
  ├─ fetch_macro_unified.py   数据底座（36指标）
  ├─ build_macro_env.py       状态机（四驱动+相变+三尺度+地区+流动性）
  ├─ macro_indicator_registry.json  指标登记表
  └─ data/  macro_series.json / macro_latest.json / macro_env.json / opinions.json
~/wiltw-pages/macro/          部署目录（gh-pages 分支）
  ├─ index.html               宏观仪表盘（三尺度+地区+资产+驱动+观点+流动性）
  └─ data/                    前端数据
```

联动脚本（读 macro_env 的板块）：
- `~/projects/trading-system/emergence_assess.py`（涌现）
- `~/projects/trading-system/metal_tracker.py`（金属面板）
- `~/projects/trading-system/metal_kondratieff.py`（金属康波验证）
- `~/projects/trading-system/metal_factor_analysis.py`（金属因素关联）
