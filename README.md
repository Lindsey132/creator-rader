# Creator Radar 博主雷达

每天自动从 YouTube 搜索博主、计算互动数据并打分，结果保存在 `data/creators.json`。
Automatically searches YouTube for creators every day, scores them, and saves results to `data/creators.json`.

## 文件结构 / Files

```
config.json                     搜索设置 / search settings
scripts/fetch_youtube.py        抓取脚本 / fetcher script
.github/workflows/fetch.yml     每日定时任务 / daily schedule
data/creators.json              结果（自动生成）/ results (auto-generated)
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

| 字段 Field | 含义 Meaning |
|---|---|
| `keywords` | 搜索关键词 / search keywords |
| `regions` | 国家代码，如 US、GB、IE、DE、JP / country codes |
| `language` | 视频语言 / video language |
| `days_back` | 只看最近 N 天发布的视频 / only videos from the last N days |
| `max_results_per_search` | 每次搜索最多几条（最多 50）/ results per search (max 50) |
| `min_subscribers` / `max_subscribers` | 粉丝量范围 / subscriber range |
| `recent_videos_to_check` | 用最近几条视频算互动率 / recent videos used for metrics |

## 打分规则 / Scoring (0–100)

- **互动率 Engagement（50 分）**：（点赞 + 评论）÷ 播放，≥5% 得满分。
  (likes + comments) ÷ views; 5%+ gets full marks.
- **触达 Reach（30 分）**：平均播放 ÷ 粉丝数，≥30% 得满分，可以识别“粉丝多但没人看”的号。
  Average views ÷ subscribers; 30%+ gets full marks. Flags channels with inactive audiences.
- **活跃度 Recency（20 分）**：14 天内更新得 20 分，30 天内得 10 分。
  Uploaded within 14 days = 20, within 30 days = 10.

## API 配额 / Quota

YouTube 免费配额是每天 10,000 单位。每次搜索消耗 100 单位，所以“关键词数 × 地区数”最好不超过 60。现在的设置是 3 × 3 = 9 次搜索，大约消耗 1,200 单位。如果配额用完，脚本会先保存已抓到的数据。
The free quota is 10,000 units/day and each search costs 100, so keep keywords × regions under about 60. The current config uses about 1,200 units. If the quota runs out, the script saves what it has.

## 手动字段 / Your own fields

每个博主都有 `status`（默认 `new`）和 `notes` 两个字段。以后网页可以用它们标记“已联系 / 已合作 / 不合适”，每天更新时不会被覆盖。
Each creator has `status` (default `new`) and `notes`, which are kept across daily updates. The dashboard will use them to mark contacted, partnered, or rejected creators.
