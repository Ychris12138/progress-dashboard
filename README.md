# 个人进度看板

[![Pages](https://github.com/Ychris12138/progress-dashboard/actions/workflows/pages.yml/badge.svg?branch=main&event=push)](https://github.com/Ychris12138/progress-dashboard/actions/workflows/pages.yml)

[打开看板](https://ychris12138.github.io/progress-dashboard/) · [部署约束](docs/PAGES.md)

本地数据引擎、前端和 Git 事务已实现，GitHub Pages 已完成首次空站部署。正式公开数据为空，生产工作流强制阻止非空业务数据。支持分类、搜索、状态筛选、项目历史、全局时间轴和本地记录入口。Git 发布当前只接受本地 bare 仓库，用于合成数据验证。

日常流程：当前工作聊天生成草稿 → 本地导入 → 完整预览 → 用户确认批次 → 显式 publish。**approve 只保存本地批准凭据；只有 publish 才应用文件并提交、推送到已初始化的本地 bare 目标。** 本轮没有发布真实数据。

## 运行

先看合成数据演示：

```sh
cd progress-dashboard
python3.12 scripts/preview_local.py --synthetic
```

打开终端打印的地址。预览包含 6 个合成项目、9 条合成记录，顶部明确标注演示；使用独立临时目录并模拟 `/progress-dashboard/` 子路径，不改动正式数据。Ctrl-C 停止服务，终端打印的预览文件保留。此命令不会自动启动浏览器。

Python 3.12+，零第三方运行依赖；锁使用 POSIX `flock`，本版支持 macOS/Linux。Git CLI 用于基准检查、初始化与发布；GitHub CLI 和认证仅在第四阶段需要。Windows 原生锁尚未适配。

在项目目录执行：

```sh
python3.12 -m unittest discover -s tests -v
python3.12 scripts/validate.py
python3.12 scripts/build.py
python3.12 -m http.server 0 --bind 127.0.0.1 --directory dist
```

端口 0 会选择空闲端口，打开终端打印的 `http://127.0.0.1:实际端口`。用 Ctrl-C 关闭服务器。页面通过 fetch 加载 JSON，不能靠双击 HTML 文件替代 HTTP 预览。只服务 dist 或专门的候选预览目录，不能把私有目录作为网站根目录。

全部主命令支持 `--repo PATH --local-root PATH`；默认私有目录为项目同级的 `progress-dashboard-local`。两个真实路径必须分离，私有目录不能在 Git 工作树内。

## 看板与记录入口

- 分类、当前状态与搜索可以组合。搜索覆盖项目名称、别名、ID、历史摘要、下一步和阻塞；多个关键词须同时匹配。筛选后的时间轴保留匹配项目的完整历史。
- 项目卡片分别选择当前状态和最近工作进展。状态更新不会覆盖工作摘要；同日日期精度导致先后不明时显示候选进展，不虚构唯一最新记录。
- 点击项目历史查看完整记录及各自状态证据。时间轴分别展示精确时刻和“当日，时间未记录”，两组布局不代表真实先后。
- “记录进展”提供当前聊天指令、指定范围补扫指令和手动 JSON 草稿。指令需自行交给具有来源访问能力的 Agent，不会从网页直接读取聊天。
- 手动草稿默认待核实，支持工作进展或单独状态更新。下载符合 `draft-v1` 的 JSON，再用 `scripts/import.py --input FILE` 导入。工具分配 `record_id` 和 `recorded_at`；网页不生成它们。
- 同一条手动记录重复下载保留草稿 ID。下载后项目固定；记录另一项工作时用“清空并另记一条”产生新 ID。已有正式记录修订仍使用本地修订接口，不由网页猜测目标记录。
- 剪贴板或下载不可用时，可从文本框手动复制。输入只存在当前页面内存，刷新会丢失；不会上传、写入浏览器存储或自动审批。下载文件和剪贴板由用户自行保管。

页面包含数据更新时间和构建时间。无法取得公开数据的 Git 修改时间时，明确显示最近录入时间且说明不含修订时间。Actions 尚未配置时显示“尚未配置”，不生成虚假链接。长期未更新不推断失败；没有百分比或效率图表，也不加载第三方 CDN。

## 开发验证

Python 是运行依赖；Node、jsdom 和 Playwright 仅用于开发测试，网页本身不依赖它们。使用 Node 24.19.0：

```sh
python3.12 -m unittest discover -s tests -v
npm ci --ignore-scripts --no-audit --no-fund
PYTHON=python3.12 npm test
node --check src/app.js
```

DOM 测试不执行真实浏览器布局。第二阶段历史结果见 [第二阶段报告](docs/PHASE2_REPORT.md)，后续 Chromium 手机视口实测见 [第四阶段报告](docs/PHASE4_REPORT.md)。浏览器测试使用固定的开发依赖，仅在 GitHub Linux runner 安装浏览器。

## 最小本地流程

以下示例是合成数据演示，只在本地使用，不要发布。

```sh
python3.12 scripts/project.py create --project-id proj_demo --name 测试项目 --category research
python3.12 scripts/import.py --input tests/fixtures/manual-draft.json
```

命令分别返回项目草稿 ID 和记录草稿 ID。把返回值代入：

```sh
python3.12 scripts/preview.py --draft PROJECT_DRAFT_ID RECORD_DRAFT_ID
python3.12 scripts/preview.py --verify BATCH_ID
python3.12 scripts/build.py --batch BATCH_ID --output /private/tmp/progress-dashboard-preview
python3.12 -m http.server 0 --bind 127.0.0.1 --directory /private/tmp/progress-dashboard-preview
```

检查返回的本地 preview.md：它包含完整候选数据、修改前后文本、文件增加/修改/删除及人工审阅提示。只有用户确认对应批次和摘要后，才执行：

```sh
python3.12 scripts/preview.py --approve BATCH_ID --digest REVIEWED_SHA256
```

### 记录与项目修订

- 项目操作：`project.py create`、`rename --project-id … --name …`、`set-category --project-id … --category …`。改名/分类以公开注册表为基准，不直接修改它；第一阶段可在测试仓库验证已有项目操作。
- 已发布记录修订：在草稿的 revision 填写 target_record_id 和两个纠正标记。record_id、project_id、recorded_at 不变。跨日修订在一个批次内移除旧位置并增加新位置。
- 来源变更或新的来源拆分会返回 needs_review 和 review_digest。先查看私有 catalog 中的候选、证据及原始草稿；用户确认后执行 `import.py --confirm DRAFT_ID --digest REVIEWED_SHA256`，再生成预览。
- 不要重造来源 unit_id 或手动草稿 draft_id。不同 ID 的人工重复事件不能被可靠自动推断，需人工合并；同一来源的拆分须沿用本地映射。

## 文件边界

| 位置 | 用途 |
|---|---|
| public/projects.json | 空初始注册表；后续只接收批准后的公开项目 |
| public/records/YYYY/MM/DD.json | 按上海发生日期保存的公开记录 |
| schemas/ | 五类 JSON Schema；跨记录规则由 Python 校验 |
| dashboard/、scripts/ | 共享逻辑及 CLI |
| tests/fixtures/ | 合成输入，禁止放真实聊天 |
| dist/ | 不提交的正式构建输出 |
| 同级私有目录 drafts/catalog.json | 原子保存草稿、来源身份映射、稳定 ID 与首次录入时间 |
| 同级私有目录 approvals/ | 冻结候选、完整预览、审批清单、批准凭据 |
| 同级私有目录 transactions/ | 发布日志、原文件备份及恢复证据 |
| 同级私有目录 bootstrap.json、publish-config.json | 初始化审批摘要和仅限本地 bare 的启用凭据 |
| 同级私有目录 source-cache/、checkpoints/ | 必要来源片段、采集事务及覆盖检查点 |

source-mappings/ 为外部项目到聊天白名单预留；事件身份映射与草稿统一保存在 catalog，以免两份文件分别更新导致不一致。config.local.json 为后续配置预留，本版命令以显式参数为准。

## Desktop 来源

工具不会自行访问 Desktop 数据库。具备 Desktop 工具的 Agent 按已选择的聊天和时间范围调用 list/read，给出最小必要的可见消息，再使用 `normalize_desktop.py` 生成来源格式，`capture.py --input FILE` 持久化。规范见 docs/CONTRACTS.md。

普通归一化默认将轮次标记为 needs_review，不自动提取正式状态。`--poc-no-record` 仅用于用户要求的接口连通性测试，不能用于跳过真实业务记录。一个采集事务完成不表示记录已批准发布。

同一来源的并发采集会拒绝冲突并要求重试。每页最多 50 轮，未覆盖范围保存续读位置；运行中轮次不推进完成水位。已完成消息重读同时比较 ID 和内容哈希。仅查询时提供的消息被纳入哈希，未选取的旧消息变化不会自动发现。

## 故障恢复

- 导入失败：修正草稿后使用同一 draft_id 重试；未知字段和 Agent 填写的 recorded_at 会被拒绝。
- 需要证据核实：先审阅本地候选再确认 digest；不能简单改 needs_review 标记跳过审阅。
- 预览拒绝：解决状态证据重叠、敏感文本、重复 ID 或过期基准，再重新生成批次。
- 候选/清单/预览/HEAD 变化：旧批准不可用；重新预览和确认。批准不防御拥有同一用户写权限者的恶意篡改。
- 采集保存后崩溃：重放原 source-result 文件；先前 ID 和 recorded_at 被复用。不要手工提前更新检查点。
- `incomplete`：按同一 scan_id、window 和返回 next_cursor 继续；有运行中轮次时另起后续增量扫描重查。游标失效需 Agent 定位已存轮次锚点，无法定位就报告缺口，不跳过。
- 文件符号链接或路径越界：改用真实、相互独立的普通目录，不关闭保护检查。
- 公开误发：未来上线后，仅删除当前 JSON 无法清除 Git 历史或他人副本；凭据暴露还须撤销。不能将自动隐私检查视为完整脱敏保证。
- Git 提交前中断：执行 `publish.py --batch BATCH_ID --recover-only`；验证后恢复本批次文件和暂存，返回 rolled_back，再重复 publish。外部修改或备份变化会停止恢复，不覆盖用户内容。
- 提交后推送失败：重复同一 publish。工具先检查远程是否已经包含提交，再决定是否重试；不生成第二个提交，不自动 reset/rebase。远程分叉则保留提交和证据，等待人工处理。

## 本地 Git 演练

完整命令及初始化审批流程见 [Git 操作说明](docs/GIT_WORKFLOW.md)。以下命令只生成固定合成数据，在新的独立目录中完成空站初始化、审批、暂存崩溃恢复、真实 bare 拒收、推送重试和远程冲突演练：

```sh
python3.12 scripts/demo_git.py --output /private/tmp/progress-dashboard-git-demo
```

目标必须尚不存在。演练结束保留 repo、remote.git、private/transactions 和 proof.json；最后故意保留一个远程冲突，供核对恢复行为，不是演练失败。此脚本不会复制真实草稿或连接 GitHub。正式项目本身没有因此初始化 Git。

## 已实现与后续

第一阶段测试涵盖独立格式、时间精度、状态选择、修订迁移、冻结审批、路径和隐私边界，以及来源故障恢复。具体实测结果见 docs/PHASE1_REPORT.md；含真实 ID 的 PoC 报告只在私有目录。

第二阶段交互和手机响应式样式已实现；后续真实浏览器验收结果以第四阶段报告为准。第三阶段已完成本地 bare 的发布和初始化验证，见 [第三阶段报告](docs/PHASE3_REPORT.md)。第四阶段已创建公开仓库并完成空站部署、PR／分支／失败保护实测，见 [部署报告](docs/PHASE4_REPORT.md)。真实进度发布仍未启用。

GitHub 上的 Python 3.12／3.14 和前端检查已实际通过。生产 Pages 工作流按 Job 最小授权，只有 deploy Job 可写 Pages。只读 Browser acceptance 工作流在独立 Linux Chromium 中检查线上空站；不在本机启动系统 Chrome。
