# ChatBI MVP 原型 — Figma 标注说明文档（Design Handoff Spec）

> 用途：指导设计师在 Figma 中还原高保真界面
> 对应产物：《ChatBI_MVP原型图.html》（视觉稿）
> 适用版本：PRD v1.0 · MVP 范围（P0 + ★核心差异）
> 目标用户视角：数据分析师 / 数据工程师
> 编制：2026-08

---

## 一、文档信息

| 项 | 内容 |
|----|------|
| 画板基准 | Desktop · 1280 × 800（最小可视宽度 1200） |
| 主题 | Dark（深色）优先，浅色为后续 Phase |
| 栅格 | 无强制栅格；三栏固定侧栏 + 弹性中栏 |
| 设计交付 | 单一 Page：`ChatBI · MVP`，含 1 个 Main Frame + 组件页 |
| 标注单位 | px（与 CSS 一致，便于开发 1:1 还原） |

---

## 二、Design Tokens（设计变量）

### 2.1 颜色 Token

| Token | HEX | 用途 |
|-------|-----|------|
| `bg.page` | `#07090d` | 页面最底层背景 |
| `bg.canvas` | `#0e1117` | 应用主背景 |
| `bg.panel` | `#161b22` | 顶栏 / 侧栏 / 右栏底色 |
| `bg.panel-2` | `#1c232d` | 卡片 / 列表项底色 |
| `bg.code` | `#0a0e13` | SQL / 日志代码区底色 |
| `line.base` | `#2a3340` | 边框 / 分割线 |
| `txt.primary` | `#e6edf3` | 主文字 |
| `txt.muted` | `#8b98a9` | 次要文字 / 标注 |
| `accent` | `#4f9cff` | 主操作 / 强调 / 链接 |
| `accent-2` | `#ff7eb6` | 渐变辅助 / ★差异化高亮 |
| `ok` | `#3ecf8e` | 成功 / 口径命中 / 日志 OK |
| `warn` | `#f0a24b` | 可编辑提示 / 告警 |
| `gradient.brand` | `#4f9cff → #ff7eb6` | Logo / 品牌渐变 |

### 2.2 字体排印（Typography）

| 角色 | 字体 | 字号 | 行高 | 字重 | 颜色 |
|------|------|------|------|------|------|
| 标题 H1 | 系统 UI | 15 | 20 | 600 | `txt.primary` |
| 副标题 | 系统 UI | 12 | 16 | 400 | `txt.muted` |
| 正文 Body | 系统 UI | 14 | 1.55 | 400 | `txt.primary` |
| 小字 Caption | 系统 UI | 12 | 16 | 400 | `txt.muted` |
| 微标 Micro | 系统 UI | 11 | 14 | 400 | `txt.muted` |
| 代码 Code | ui-monospace / Menlo / Consolas | 12.5 | 1.6 | 400 | `#cfe3ff` |
| 代码关键字 | 同 Code | 12.5 | — | — | `#ff7eb6`（kw） |
| 代码函数 | 同 Code | 12.5 | — | — | `#3ecf8e`（fn） |
| 代码字符串 | 同 Code | 12.5 | — | — | `#f0a24b`（str） |

> 系统 UI 字体栈：`-apple-system, "Segoe UI", "PingFang SC", Roboto, sans-serif`

### 2.3 间距与圆角（Spacing & Radius）

| Token | 值 | 用途 |
|------|----|------|
| `space.xs` | 4 | 芯片内边距 / 微调 |
| `space.sm` | 8 | 元素间距 / 按钮内边距横 |
| `space.md` | 12 | 卡片内边距 / 区块间距 |
| `space.lg` | 16–18 | 大区内边距 / 对话区 padding |
| `radius.sm` | 7–8 | 按钮 / 输入 / 标签 |
| `radius.md` | 10–11 | 卡片 / 消息气泡 |
| `radius.lg` | 12 | 顶栏（顶部圆角） |
| `radius.pill` | 20 | Chip / Badge / 头像圆 |

---

## 三、画板与页面结构

### 3.1 信息架构（Figma 图层树）

```
Page: ChatBI · MVP
├─ Frame: Desktop-1280 (1280 × 800)
│  ├─ Topbar (1280 × 52)
│  ├─ Body (1280 × 748)  [横向 Auto-layout]
│  │  ├─ Sidebar (210 × 748)
│  │  ├─ Center (flex × 748)
│  │  │  ├─ Chat (滚动区)
│  │  │  └─ InputBar (底)
│  │  └─ RightPanel (380 × 748)
│  └─ (设计标注层不进画板，见 §七)
└─ Page: Components (组件库，见 §五)
```

### 3.2 三栏尺寸标注

```
┌──────── 1280px ────────────────────────────────┐
│ Topbar  H=52  pad:12/18  radius-lg(顶部)         │
├──────────┬────────────────────────┬─────────────┤
│ Sidebar  │  Center (flex:1)       │ Right 380px │
│ W=210    │  Chat  +  InputBar     │             │
│ pad:14   │  pad:18                │ pad:14      │
└──────────┴────────────────────────┴─────────────┘
 总高 800   栏高 = 800-52 = 748
```

---

## 四、区域组件标注（逐区域）

### 4.1 顶栏 Topbar
- **尺寸**：1280 × 52，底部 `radius-lg`，下边框 `line.base`
- **结构**：Logo(26×26, radius 7, 渐变) · 标题组(左) · Nav(中, margin-left 18) · 工具组(右)
- **Nav 项**：问数(active) / 资产库 / 语义层 / 数据源；active = `bg.panel-2` 底 + `txt.primary`，其余 `txt.muted`
- **右工具**：`● 私有化部署`(micro, muted) + Avatar(26×26, 圆, `bg.panel-2`)
- **PRD**：F-502 / F-503（私有化/权限入口）

### 4.2 左导航 Sidebar
- **尺寸**：210 × 748，右边框 `line.base`，`bg.panel`，pad 14
- **分组**（每组 title 11px uppercase muted + 列表项）：
  - 我的资产：列表项 `Item`(radius 7, `bg.panel-2`, 13px) + 复用次数 micro 右对齐
  - 指标中心（唯一事实源）：指标项带 `∑` 图标(accent) + 口径 micro
  - 数据源（跨源中立）：项带 `▣` 图标 + 类型 micro(Hive/MySQL)
- **PRD**：F-201 / F-203 / F-306 / F-501

### 4.3 中栏对话区 Center
- **消息气泡**
  - 用户：`bg.accent` + 白字，右对齐，max-width 86%，`radius-md` 右下角 3px
  - 机器人：`bg.panel` + 边框 `line.base`，左对齐，`radius-md` 左下角 3px
  - 说话人标签：11px `txt.muted`（"你 · 数据分析师" / "ChatBI 副驾"）
- **意图 Chips**（bot 消息内）：`bg #10202c` + 边框 + `accent` 字，格式 `指标 <b>成交额</b>`；命中值用 `ok` 色
- **SQL 草稿卡 SQLCard**（核心组件，见 §五）：含头部(✏️可编辑 + 标题) + `<pre>` 代码区(语法高亮) + 运行行(运行/保存按钮)
- **输入栏 InputBar**：底部固定，`bg.panel`，上边框；Input(flex, `bg.panel-2`, radius 8) + 发送按钮
- **PRD**：F-101(多轮) / F-102(术语) / F-104(澄清) / F-301(可见) / F-302(可改体现在右栏)

### 4.4 右面板 RightPanel
- **SQL 编辑器卡**：标题 `SQL 编辑器` + Badge `人在回路 F-303`(`ok` 底色#133) → `<textarea>`(`bg.code`, `txt.code` 色, mono) → 运行/保存按钮行
- **结果卡**：标题 `查询结果` + Badge `实时执行 F-103` → `Table`(th `bg.code`+muted, td 边框; 数值列右对齐 `ok`) → 下钻提示 micro
- **日志卡**：标题 `全链路日志（可审计·可回放）` + Badge `F-304 ★` → `LogList`(mono 11px, `s-ok` 行 `ok` 色)
- **PRD**：F-303★ / F-103 / F-304★ / F-401(下钻) / F-305(导出)

---

## 五、组件库（Components）清单

> 在 Figma `Components` 页建立以下主组件 + Variant，供全页复用。

| 组件 | 变体 Variants | 关键属性 |
|------|--------------|----------|
| `Button/Primary` | default / hover / disabled | `bg.accent`+白字, radius 8, pad 8/16, 13px |
| `Button/Ghost` | default / hover | `bg.panel-2`+边框+`txt.primary` |
| `Chip` | default / hit | 圆角 20, micro 11px |
| `Badge` | ok / accent | 圆角 20, 10px, `#133`+`ok` |
| `NavItem` | active / idle | 13px, pad 6/12, radius 8 |
| `SidebarItem` | default | `bg.panel-2`, radius 7, 13px, 图标 accent |
| `MessageBubble` | user / bot | 见 §4.3 |
| `SQLCard` | draft / editing | 头部 + 代码 + 运行行 |
| `DataTable` | default / empty | th muted, td 边框, 数值 ok |
| `LogList` | default / ok / error | mono 11px |
| `Avatar` | default | 26×26 圆, `bg.panel-2` |
| `Input` | default / focus | `bg.panel-2`, focus 边框 accent |

**图标**：统一 16px / 24px 网格，线性风格（stroke 1.5），色 `accent` 或 `txt.muted`。

---

## 六、交互与状态标注

### 6.1 人在回路（核心流程，必须体现）
```
提问 ──▶ 生成SQL草稿(可见,默认不执行)
   ──▶ 用户可编辑 textarea
   ──▶ 点击「运行」(显式批准) ──▶ 执行 ──▶ 结果+日志
写操作(INSERT/UPDATE/DELETE/DROP) ──▶ 禁用/拦截提示
```

### 6.2 组件状态清单
| 组件 | 状态 |
|------|------|
| Button/Primary | default / hover(亮度+8%) / disabled(40%透明) |
| Input | default / focus(边框 accent) |
| SQLCard | draft(只读展示) / editing(可编辑, 边框 warn 提示) |
| DataTable | data / empty("尚未运行" muted) / loading(skeleton) |
| LogList | 各 step 行（understand/generate/execute/save/error） |

### 6.3 空态 / 异常态
- 结果区空态：`尚未运行`（muted 13px）
- 执行失败：`⚠️ 执行失败：<原因>`（`#ff6b6b`）
- 未识别意图：bot 回 `没太懂，请换个说法 + 示例`（进入澄清，对应 F-104）

---

## 七、PRD 功能映射表（界面 → F-ID）

| 界面区域 | PRD 功能 | 优先级 |
|----------|----------|--------|
| 左栏·指标中心 | F-201 / F-203 语义层/唯一事实源 | P0 |
| 中栏·意图 chips | F-102 / F-104 术语理解/澄清 | P0/P1 |
| 中栏·SQL 草稿卡 | F-301 可见 / F-101 多轮 | P0 ★ |
| 右栏·SQL 编辑器 | F-302 可编辑改写 | P0 ★ |
| 右栏·运行按钮 | F-303 人在回路批准 | P0 ★ |
| 右栏·查询结果 | F-103 实时 / F-401 下钻 / F-305 导出 | P0/P1 |
| 右栏·全链路日志 | F-304 可审计可回放 | P0 ★ |
| 左栏·我的资产 | F-306 沉淀 / F-204 feedback | P1 |
| 顶栏·私有化 | F-501 / F-502 / F-503 跨源/私有化/权限 | P0/P1 |

> ★ = 核心差异化功能（竞品普遍薄弱，见《竞品功能点逐项拆解表》C 域）

---

## 八、切图与交付清单

**需切图 / 矢量资源**
- Logo（渐变 C 标，导出 SVG + 24/48px PNG）
- 导航/侧栏图标集：`★ ▣ ∑ ＋ ▣`（线性 SVG，16px）
- 空态插画（可选，Phase 2）

**交付文件（设计师产出）**
- `ChatBI-MVP.fig`：含 Main Frame + Components 页 + 1 套 Dark 变体
- 标注：在 Figma 使用自带 Inspect 标注（px/color/type），本文件为补充规格
- 交接开发：导出 CSS Variables（见 §2 Tokens）供 1:1 还原

**标注注意事项**
1. 所有尺寸以 px 标注，与 CSS 1:1；
2. 代码区语法高亮颜色（kw/fn/str）需严格使用 §2.1 指定 HEX；
3. 三栏中 Center 为弹性宽度，Sidebar/Right 固定，勿用绝对定位破坏流式布局；
4. 人在回路的"默认不执行"是产品红线， UI 上"运行"必须是显式动作。

---

## 九、适配说明（后续 Phase）

| 断点 | 布局 |
|------|------|
| ≥1200 | 三栏完整（本 MVP 基准） |
| 900–1199 | 右栏改为抽屉/底部 Tab |
| <900 | 单栏：对话为主，SQL/结果/日志用底部 Tab 切换 |

> 本 MVP 仅交付 Desktop ≥1200 三栏；移动端为后续迭代。

---

*附：本标注文档与《ChatBI_MVP原型图.html》一一对应，设计师可对照视觉稿逐区域还原；开发可结合 `/workspace/mvp/` 功能原型（代码结构）理解交互逻辑。*
