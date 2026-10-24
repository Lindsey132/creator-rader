# Creator Radar 博主雷达

每天自动从 YouTube 搜索博主、计算互动数据并打分，结果保存在 `data/creators.json`。
Automatically searches YouTube for creators every day, scores them, and saves results to `data/creators.json`.

## 文件结构 / Files

```
config.json                     搜索设置 / search settings
scripts/fetch_youtube.py        抓取脚本 / fetcher script
.github/workflows/fetch.yml     每日定时任务 / daily schedule
data/README.md                  结果说明（自动生成）/ results guide (auto-generated)
data/<类别>.csv                 每个类别一张表 / one table per category
data/creators.json              原始数据 / raw data
```

## 设置步骤 / Setup

1. **新建仓库 / Create a repo**：在 GitHub 新建一个仓库（可以设为 Private），把这个文件夹里的所有文件上传进去，注意 `.github` 文件夹也要一起上传。
   Create a new GitHub repo (private is fine) and upload everything in this folder, including the `.github` folder.
2. **添加 API Key / Add the key**：仓库 → Settings → Secrets and variables → Actions → New repository secret，名称填 `YOUTUBE_API_KEY`，值填你的 Key。
   Repo → Settings → Secrets and variables → Actions → New repository secret. Name: `YOUTUBE_API_KEY`.
3. **允许写入 / Allow writes**：Settings → Actions → General → Workflow permissions → 选 *Read and write permissions*。
   Settings → Actions → General → Workflow permissions → *Read and write permissions*.
4. **手动跑一次 / First run**：Actions 标签页 → *Fetch creators (daily)* → *Run workflow*。跑完后 `data/creators.json` 就会出现。之后每天自动运行。
   Actions tab → *Fetch creators (daily)* → *Run workflow*. After that it runs daily.

## 修改搜索条件 / Changing the search

直接在 GitHub 网页上编辑 `config.json`：
Edit `config.json` on GitHub:

**查看结果 / Results：** 打开 [`data`](data) 文件夹，说明页里有每个类别表格的链接。
Open the [`data`](data) folder; its guide links to one table per category.

**全局设置 / Global settings**

| 字段 Field | 含义 Meaning |
|---|---|
| `regions` | 主要搜索地区，每个关键词都会搜 / main search regions, used for every keyword |
| `secondary_regions` | 次要地区，只搜每个类别的前 `secondary_keywords_per_category` 个关键词 / extra regions, used only for each category's first keyword(s) |
| `priority_country` | 表格里优先排在前面的国家 / country listed first in every table |
| `brands_to_track` / `big_brands_to_track` | 在视频标题和描述里查找的品牌，用来判断博主是否测评或合作过 / brands looked for in video titles and descriptions to spot past reviews or collabs |
| `only_countries` | 只保留这些国家的博主（留空 `[]` 表示不限）/ keep only creators from these countries (`[]` = any) |
| `keep_unknown_country` | 没填国家的博主是否保留 / keep creators with no country set |
| `language` | 视频语言 / video language |
| `days_back` | 只搜最近 N 天发布的视频 / only search videos from the last N days |
| `max_results_per_search` | 每次搜索最多几条（最多 50）/ results per search (max 50) |
| `recent_videos_to_check` | 用最近几条视频计算数据 / recent videos used for metrics |

**类别 / Categories**（`categories` 里每一项是一张表 / each entry becomes one table）

| 字段 Field | 含义 Meaning |
|---|---|
| `id` | 表格文件名，如 `tech-long` → `data/tech-long.csv` / table file name |
| `name` / `description` | 类别名称和说明 / category name and explanation |
| `keywords` | 搜索词 / search keywords |
| `search_duration` | 可选：`short`(<4分钟) `medium`(4–20分钟) `long`(>20分钟) / optional video-length filter for search |
| `min_median_minutes` | 博主视频的典型时长至少几分钟（0 = 不限）/ minimum typical video length (0 = any) |
| `must_match_any` | 频道名、简介或视频标题里必须出现其中一个词，用来排除不相关的号 / at least one of these words must appear, to drop off-topic channels |
| `min_subscribers` / `max_subscribers` | 粉丝量范围 / subscriber range |

想加新类别：复制一个类别，改 `id`、`name` 和关键词即可。每个关键词 × 每个地区消耗 100 配额，所有类别加起来最好不超过 60 次搜索。
To add a category, copy one and change its `id`, `name` and keywords. Each keyword × region costs 100 quota units; keep the total under about 60 searches.

## 打分规则 / Scoring (0–100)

- **互动率 Engagement（50 分）**：（点赞 + 评论）÷ 播放，≥5% 得满分。
  (likes + comments) ÷ views; 5%+ gets full marks.
- **触达 Reach（30 分）**：平均播放 ÷ 粉丝数，≥30% 得满分，可以识别“粉丝多但没人看”的号。
  Average views ÷ subscribers; 30%+ gets full marks. Flags channels with inactive audiences.
- **活跃度 Recency（20 分）**：14 天内更新得 20 分，30 天内得 10 分。
  Uploaded within 14 days = 20, within 30 days = 10.

## API 配额 / Quota

YouTube 免费配额是每天 10,000 单位。每次搜索消耗 100 单位，所以“关键词数 × 地区数”最好不超过 60。现在的设置一共 40 次搜索，大约消耗 5,000–6,000 单位。如果配额用完，脚本会先保存已抓到的数据。
The free quota is 10,000 units/day and each search costs 100, so keep keywords × regions under about 60. The current config runs 40 searches, about 5,000–6,000 units. If the quota runs out, the script saves what it has.

## 手动字段 / Your own fields

每个博主都有 `status`（默认 `new`）和 `notes` 两个字段。以后网页可以用它们标记“已联系 / 已合作 / 不合适”，每天更新时不会被覆盖。
Each creator has `status` (default `new`) and `notes`, which are kept across daily updates. The dashboard will use them to mark contacted, partnered, or rejected creators.
