# HomeLens SG

HomeLens SG 是一个面向新加坡 HDB 转售住房的可解释推荐系统。

用户输入预算、房型、区域、面积等需求后，系统会先筛选满足硬条件的候选，再进行综合排名，并说明推荐理由。

> 当前推荐的是根据历史成交数据整理出的“代表性楼栋＋房型”，不是实时在售房源，也不是正式估值。

## 1. 我们已经实现了什么

### 1.1 数据下载、清洗和知识库

系统可以从 data.gov.sg 下载官方 HDB 转售数据，并处理日期、价格、面积、楼层、剩余租期、缺失值和异常值。

当前本机数据：

| 内容 | 当前结果 |
| --- | ---: |
| 原始 HDB 成交记录 | 235,356条 |
| 清洗后记录 | 235,355条 |
| 完整分析月份 | 2017年1月－2026年6月 |
| 候选知识库 | 7,730个楼栋＋房型候选 |

2026年7月在下载时还没有结束，因此记录会保留，但不会进入推荐、EDA和模型实验。

知识库使用最近24个完整月份的数据，并按下面的单位汇总：

```text
区域 + 楼栋 + 街道 + 房型
```

每个候选包含历史价格范围、面积、楼层、剩余租期、交易数量、最近交易时间和价格趋势。

目前推荐范围是：

- 只包含 HDB 转售住房；
- 只包含官方历史数据中出现过的楼栋；
- 每个候选至少有3笔近期交易；
- 覆盖26个标准 HDB town；
- 不包含私人公寓和实时挂牌房源。

### 1.2 不依赖大模型的中英文需求解析

没有 OpenAI API Key 时，系统使用规则理解用户输入：

- 正则表达式识别预算、面积、租期和距离；
- 关键词识别“宽敞”“便宜”“靠近地铁”等偏好；
- 词典识别房型和 HDB town。

例如：

```text
I want a spacious 4-room flat under 650k, preferably in Tampines.
```

会被识别为：

```json
{
  "budget": 650000,
  "flat_types": ["4 ROOM"],
  "preferred_towns": ["TAMPINES"],
  "weights": {
    "affordability": 0.32,
    "space": 0.324,
    "lease": 0.13,
    "location": 0.27,
    "transit": 0.12,
    "amenities": 0.06,
    "market_activity": 0.04
  }
}
```

中文输入也可以识别：

```text
预算65万以内，想要四房，最好在Tampines，面积大一点。
```

### 1.3 硬条件筛选和推荐排名

推荐流程分为四步：

1. 把自然语言转换成结构化需求；
2. 先应用预算、房型、必须区域、最低面积和最低租期等硬条件；
3. 对满足硬条件的候选，根据价格、面积、租期、位置和数据量进行排名；
4. 为最终结果增加随机森林参考价格和推荐理由。

预算筛选使用近期成交价格的 **75%分位数**，比只看中位数更保守。

如果用户说 `preferably in Tampines`，Tampines 是软偏好，其他区域仍可能出现；如果说 `only in Tampines`，Tampines 会成为硬条件。

系统还会标记低样本候选、Pareto优秀选项和缺失数据，并尽量避免所有结果集中在同一个 town。

### 1.4 随机森林参考价格

项目比较了历史中位数基线和随机森林回归模型。模型使用区域、房型、楼层、面积、剩余租期和交易时间等特征。

当前时间测试集结果：

| 指标 | 随机森林结果 |
| --- | ---: |
| MAE | 约 S$39,686 |
| MAPE | 约 5.90% |
| R² | 约 0.928 |

随机森林只提供参考价格，不参与预算硬筛选，也不代表正式房屋估值。

### 1.5 网页、API、EDA和测试

项目已经提供：

- 浏览器网页；
- JSON API；
- 命令行推荐；
- 五张 EDA 图表；
- 36项自动化测试。

推荐结果会展示历史价格范围、面积、租期、交易数量、综合分数、ML参考价格、推荐理由和数据不足提示。

## 2. 还有哪些没有实现

| 功能 | 当前状态 |
| --- | --- |
| OneMap楼栋坐标 | 客户端和计算代码已写好，但凭证未配置，当前0个候选有坐标 |
| 附近设施结果 | MRT、巴士站、公园和小贩中心数据已下载，但尚未与楼栋匹配 |
| 任意地点附近找房 | 尚不支持，例如“找NUS附近5公里内的房子”目前无法完成 |
| 实际步行或通勤时间 | 尚未实现；现有地理算法只能计算直线距离 |
| LTA实时交通 | 尚未接入巴士班次、拥挤程度和实际路线 |
| 实时在售房源 | 尚未爬取商业房产网站，也没有实时挂牌价格 |
| OpenAI大模型解析 | 接口已预留，但API Key为空且默认关闭 |
| 私人公寓 | 当前只覆盖HDB转售住房 |
| 人工用户评价 | 留待小组后续完成 |

关于位置功能，需要特别注意：

- 当前规则主要识别26个标准 HDB town；
- 系统还不能把 NUS、公司地址或任意地标作为搜索中心；
- OneMap 尚未运行，所以现在不能准确展示推荐楼栋附近的设施；
- 如果用户要求“800米内必须有MRT”，系统会提示缺少地理证据，而不会编造距离；
- “我不想住在Bedok”目前只能被识别并提示，还不能保证结果一定排除Bedok。

## 3. 如何测试已经实现的功能

建议使用 Python 3.10或更高版本。

### 3.1 安装

```bash
cd "/Users/tab/Documents/2026NUS/Web mining/homelens-sg"
python3 -m pip install -e .
```

### 3.2 自动化测试

```bash
python3 -m unittest discover -s tests -v
```

预期看到：

```text
Ran 36 tests
OK
```

如果运行环境禁止本地端口，HTTP测试可能显示一次 `skipped`，其他测试仍应通过。

### 3.3 命令行推荐

```bash
python3 scripts/run_demo.py \
  --query "I want a spacious 4-room flat under 650k, preferably in Tampines" \
  --budget 650000 \
  --top-k 5
```

### 3.4 网页测试

```bash
python3 scripts/serve.py --port 8000
```

浏览器打开：

```text
http://127.0.0.1:8000
```

建议测试：

| 输入 | 预期结果 |
| --- | --- |
| `A spacious 4-room flat under 650k, preferably in Tampines` | 正常返回推荐并提高面积和区域权重 |
| `预算65万以内，想要四房，最好在Tampines` | 能识别中文预算、房型和区域 |
| `4-room under 100k` | 没有精确结果，不会偷偷放宽预算 |
| `4-room under 650k, within 800m of MRT` | 提示目前没有OneMap坐标，无法验证MRT距离 |

按 `Ctrl+C` 停止服务器。

### 3.5 API测试

服务器运行时，在另一个终端执行：

```bash
curl http://127.0.0.1:8000/api/health | python3 -m json.tool
```

```bash
curl -X POST http://127.0.0.1:8000/api/recommend \
  -H "Content-Type: application/json" \
  -d '{
    "query": "预算65万以内，想要四房，最好在Tampines",
    "top_k": 5
  }' | python3 -m json.tool
```

查看模型指标和图表：

```bash
python3 -m json.tool artifacts/metrics/price_model.json
```

```text
artifacts/figures/
```

## 4. 从GitHub克隆后怎么测试

大型原始数据、处理后CSV和模型文件不会上传到GitHub。小组成员刚克隆项目时，可以先用离线小数据测试：

```bash
python3 -m pip install -e .
python3 scripts/build_dataset.py --fixture
python3 scripts/train_model.py --trees 12
python3 -m unittest discover -s tests -v
python3 scripts/serve.py --port 8000
```

如果需要重新生成完整数据和研究结果：

```bash
python3 scripts/build_dataset.py
python3 scripts/download_layers.py
python3 scripts/train_model.py --trees 80
python3 scripts/explore_data.py
```

完整流程需要网络，并且下载和训练会花费一些时间。

## 5. 后续连接OneMap

不要把API Key发到群聊或提交到GitHub。

```bash
cp .env.example .env
```

在 `.env` 中填写 OneMap Token，或者填写 OneMap邮箱和密码。建议先测试20个地址：

```bash
python3 scripts/enrich_geospatial.py --limit 20
```

确认地址匹配正常后再运行全部地址：

```bash
python3 scripts/enrich_geospatial.py
```

## 6. 主要目录

```text
src/homelens/        核心代码
scripts/             数据、训练和运行脚本
tests/               自动化测试
data/                原始与处理后数据
artifacts/           模型、指标和图表
docs/                项目提案和方法说明
.env.example         API配置模板
```

更完整的说明在：

- `docs/PROJECT_PROPOSAL.md`
- `docs/METHODOLOGY.md`
- `docs/DATA_SOURCES.md`
- `docs/ARCHITECTURE.md`

## 一句话总结

我们已经完成了HDB数据处理、知识库、中英文规则解析、硬条件筛选、多条件推荐、随机森林参考价格、网页、API、EDA和自动测试；OneMap地理增强、任意地点附近找房、实时交通、实时房源、大模型解析和人工评价仍需后续完成。
