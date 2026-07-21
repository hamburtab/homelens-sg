# SG HomeRadar / HomeLens SG

SG HomeRadar 是一个面向新加坡 HDB 的可解释找房与区域探索系统，对应 proposal 中的两条核心交互路径：

- **Macro Exploration**：在 55 个 URA planning areas 和 332 个 subzones 上探索交通、餐饮、购物、教育、自然与休闲生活便利度。
- **Micro Retrieval**：用中英文自然语言描述预算、房型、区域、面积、租期和交通要求，系统先执行硬条件，再对历史证据进行多目标排名并解释原因。

系统把官方 HDB 历史成交、经许可分批获取的 PropertyGuru 租售挂牌、官方地理设施以及聚合社区证据整合进同一产品。它是课程研究与决策支持工具，不是估价服务或完整市场库存。

## 已实现功能

### 统一网页产品

- 精美、响应式的 React 单页界面；
- 新加坡 planning area / subzone 交互地图；
- 真实生活便利度热力着色与六维证据面板；
- 买房、租房挂牌筛选目录；
- 自然语言推荐表单、AI/规则解析切换；
- OneMap 任意新加坡 POI/地址检索、候选确认与地图定位；
- 以确认地点为圆心的直线距离硬筛选、排序、地图范围圈和房源距离展示；
- 推荐卡、证据强度、Pareto trade-off 标记；
- 最多 3 个候选的并排比较；
- 定期挂牌快照与历史推荐结果联动；
- 方法、模型、数据覆盖和未实现能力说明。

### 推荐与模型

- 预算、房型、指定 town、最小面积、最小剩余租期和 MRT 距离硬条件；
- 用户可输入 “NUS”“VivoCity” 或完整地址；LLM/规则只提取地点文本，后端 OneMap 才负责解析坐标；
- affordability、space、lease、location、transit、amenities 和 market activity 多目标排名；
- 缺失证据不会被当作 0，也不会偷偷放宽硬条件；
- 最近 24 个完整月份的 7,730 个 HDB 楼栋＋房型候选；
- 随机森林仅提供参考价格，历史 75% 分位价格继续控制预算筛选；
- 时间留出测试约为 MAPE 5.9%、R² 0.928。

### 当前产品数据

| 数据 | 当前规模 | 产品用途 |
| --- | ---: | --- |
| HDB 历史成交 | 235,355 条清洗记录 | 价格、面积、租期、趋势和模型 |
| HDB 候选知识库 | 7,730 条 | 推荐与区域市场画像 |
| 买房挂牌 | 6,359 条唯一挂牌 | 部分市场快照与推荐联动 |
| 租房挂牌 | 8,041 条 | 租房目录与地图 |
| Planning areas | 55 | 宏观探索 |
| Subzones | 332 | 六维生活便利度画像 |

地址解析没有伪造位置：

- 买房挂牌 5,255 / 6,359（82.6%）可以通过历史 HDB 地址或相同租房地址确定位置；
- 租房挂牌 7,932 / 8,041（98.6%）带有效坐标；
- 对仍无精确坐标的地址，仅当历史 HDB 楼栋证明该街道全部属于同一 planning area 时，才补充区域级判断；因此买房/租房的 planning-area 可筛选覆盖分别达到 95.9% / 99.3%；
- 无法可靠定位的挂牌仍保留在列表中，但不显示地图 marker；
- `locationSource` 与 `areaSource` 分别说明地图点和区域判断的证据来源。

## 快速运行

需要 Python 3.10+ 和 Node.js。

```bash
python3 -m pip install -e .
cd map
npm install
npm run build
cd ..
python3 scripts/serve.py --port 8000
```

打开：

```text
http://127.0.0.1:8000
```

Python 服务会同时提供生产版网页和 `/api/*` 推荐接口。

任意地点搜索需要 OneMap token 或 OneMap 账号凭证。它们只放在本机 `.env`，不会发送到浏览器：

```text
ONEMAP_TOKEN=...
# 或同时配置 ONEMAP_EMAIL 与 ONEMAP_PASSWORD
```

## 重新生成产品数据

仓库已包含可直接运行的产品数据。只有原始/组员数据发生变化时才需要执行：

```bash
python3 scripts/enrich_existing_candidates.py
python3 scripts/build_product_data.py
cd map && npm run build
```

其中：

- `enrich_existing_candidates.py` 使用已有楼栋坐标和官方 MRT、巴士、小贩中心、公园图层计算直线距离与设施数量，不请求新的地理 API；
- `build_product_data.py` 合并挂牌、按最新 `scraped_at` 去重、标准化地址、定位 planning area/subzone，并生成隐私安全的前端 JSON；
- 组员原始文件保持不变，所有产品文件都可从来源重新生成。

## API

### `GET /api/health`

返回知识库、模型、LLM、挂牌和数据日期状态。

### `GET /api/overview`

返回 health 与产品数据覆盖摘要。

### `POST /api/recommend`

示例：

```json
{
  "query": "预算65万以内，想要四房，最好在Tampines，靠近地铁",
  "budget": 650000,
  "flat_types": ["4 ROOM"],
  "preferred_towns": ["TAMPINES"],
  "top_k": 8,
  "use_llm": false
}
```

返回历史推荐、分数拆解、解释、模型参考价、警告以及最多 12 条部分实时买房匹配。

### `GET /api/locations/search?q=NUS&limit=5`

返回 OneMap 的新加坡地点候选及其 planning area/subzone。用户必须确认候选后，前端才把 `anchor_latitude`、`anchor_longitude` 和可选的 `max_anchor_distance_m` 交给推荐接口。坐标不由 LLM 生成。

自然语言也可写成 `A 4-room under 650k within 3km of NUS`。第一次请求会返回 `location_confirmation_required` 和候选；确认后再次请求才计算推荐。当前距离采用 Haversine 直线距离，不代表步行、驾车或公共交通路线。

## LLM 中转站

项目支持 OpenAI Responses API 兼容中转站。真实凭证只放在本机 `.env`：

```text
OPENAI_API_KEY=...
OPENAI_BASE_URL=...
OPENAI_MODEL=...
HOMELENS_ENABLE_LLM=true
```

没有 LLM 或调用失败时，系统自动回退到确定性中英文规则解析。模型只负责意图提取，不控制硬筛选和最终事实。

## 测试

```bash
python3 -m unittest discover -s tests -v
cd map && npm run build
```

当前为 52 项 Python 测试；在限制本地 socket 的沙箱中，HTTP loopback 测试会跳过，其余测试通过。前端 lint、TypeScript 与生产构建也已通过；真实 OneMap NUS 搜索、地点确认和 3 km 硬筛选已完成本机端到端验收。

## 隐私与数据边界

- 公共前端不包含 PropertyGuru `raw_listing_text` 或内部 source reference；
- Google 原始评论文本、作者名和作者 URL 不进入公共前端；
- 页面只显示社区聚合评分、place 数和 review evidence 数；
- 买房数据为不连续页面的课程研究快照：当前解析第 1–145、301–500 页；146–185 页原始页面待导入，第 186–300 页及第 500 页以后仍存在缺口；
- 没有实现每周自动调度，这是当前明确的项目范围。

## 明确保留的未来能力

页面已经为下列能力显示 `Planned` 或禁用占位，但不会假装已经实现：

- 基于道路网络的步行时间与真实通勤路线；
- 无法通过地址匹配的挂牌精确坐标；
- 完整实时买房库存与自动每周更新；
- 私人公寓历史推荐模型；
- 需要 LTA 实时线路/拥挤度数据的功能。

更详细的数据来源、目录职责和交接状态见 `docs/`、`artifacts/manifests/` 与 `CODEX_PROJECT_HANDOFF.md`。
