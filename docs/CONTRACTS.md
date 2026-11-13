# 数据、审批与读取接口

## 规范与校验

schemas 中五类文件使用 JSON Schema 2020-12。运行时采用针对这些具体格式的标准库校验函数，不实现通用 JSON Schema 引擎。公开 daily 文件是 `{schema_version:1,records:[…]}`，注册表是 `{schema_version:1,projects:[…]}`。拒绝重复 JSON 键、NaN、额外字段、不合法时间和重复 ID。

public-record 使用完整 state_snapshot；两个状态字段同时为空或同时非空。progress 代表实际工作，state_update 只改变状态证据。快照 status 枚举为 planned/active/blocked/paused/done，next_step 和 blocker 可以为 null。

日期是上海整日不确定区间 `[00:00,次日00:00)`，仅作比较，不显示为零点。精确时刻先转换上海时区。日期证据与当日时刻相交；不同快照相交即拒绝。最新进展采用时间偏序的极大元素，同日未知时刻与已知最新时刻可以并列。

## 草稿与来源身份

draft-v1 包含 draft_id、公开内容字段、source、evidence、verification、revision，不接受 recorded_at 或 record_id。import 创建新的公开对象，写入工具分配的 rec_ ID 和首次时间。来源身份键由 source_id、turn_id、unit_id 构成；content_sha256 用于变化检测，不能把哈希变化当新事件。

source.item_ids 是证据消息列表；content_sha256 是按 item_id 排序的 `{item_id,sha256}` 数组的规范 JSON 哈希。消息 sha256 对 UTF-8 原文计算，原文不做 Unicode 归一化。一个轮次的新 unit_id 若已有其他单位，会强制待核实。

source-result 含 source_id、host_id、scan_id、window、cursor、next_cursor、has_more、anchor_reached 和 turns。turn 含 turn_id、started_at、status、必要 items、outcome、reason 和 drafts。items 含 item_id、text、sha256。轮次状态只接受 completed/in_progress/failed；outcome 只接受 generated/no_record/needs_review。

anchor_reached 是适配器根据实际轮次边界给出的覆盖声明；capture 无法独立观察 Desktop 历史来替它作证。未完成轮次不得生成候选。窗口固定为扫描开始时的上下界；不能在续页期间改变。默认从最新页开始，旧页必须连接前页 next_cursor。

## 采集持久化

source page 先原子落盘、读回校验。逐条导入幂等草稿后，原子写入包含完整处理结果和草稿/ID 映射快照的 committed receipt，再写 scan 状态，最后更新 checkpoint。任一中断都可重放同一 page；不能在 receipt 之前推进检查点。

scan 记录历史翻页进度；checkpoint.completed_through 表示完整连续覆盖的完成水位，二者不是同一个游标。50 轮是读取上限，不是成功条件。有历史缺口时只保存部分 receipt，不推进完成水位。有未完成轮次时保守保持旧水位，后续新扫描重读。

真实适配器应复查最近 5 个完成轮次，并保留原选择范围以确保哈希可比。当前 Python 提供归一化、持久化和变化检测；工具分页与失效游标重新定位仍由具备工具的 Agent 完成，不宣称已有独立自动抓取服务。

## 批次与哈希

所有候选文件为 UTF-8、LF、键排序、紧凑 separators、禁止 NaN、末尾一个 LF。项目按 project_id、记录按 record_id、操作按文件路径排序。JSON 数组顺序不在哈希阶段偷偷改动。

preview 冻结完整候选数据集。manifest 同时包含 base_public、files 全集哈希及 add/modify/delete 差异，包含 target、base_commit、draft_ids、record_ids、created_at、preview_sha256。批次摘要是 manifest 的精确规范字节 SHA-256。完整预览包含旧/新 diff 和全部候选。批准凭据引用摘要，不回写 manifest。

verify 同时检查 manifest 规范字节、seal、预览、候选数据集、公开基准及 Git HEAD/remote。未初始化 Git 时 base_commit 和 repository 为 null，允许本地预览；后续初始化使旧批准失效。第三阶段将冻结内容验证与当前基准验证分开：恢复时仍验证冻结内容与批准凭据，但通过已批准父提交、文件集合与 blob 哈希确认已经产生的提交，不要求 HEAD 倒退回旧基准。

## 第二阶段展示与记录接口

第二阶段没有修改五类数据 Schema。`build.py` 仍是正式、候选和合成预览的唯一构建入口：默认只读 public；`--batch` 校验冻结候选；`--synthetic` 仅读取固定的 `tests/fixtures/dashboard-demo.json`。后两者互斥，必须显式输出到仓库及私有目录之外。演示构建要求 `synthetic:true` 标记，并通过相同公开数据校验。

构建仅输出 index.html、styles.css、app.js、data.json、build.json。data.json 是展示模型：projects 保存项目、完整最新快照、证据时间、最新进展候选和最近录入时间；timeline 按上海日期分组，timed/untimed 分开稳定排序。UI 不重新猜测状态或合并快照。

build.json 包含 built_at、commit、local_preview、synthetic、actions_url、data_changed_at。冻结候选使用批次创建时间，正式 Git 数据使用最近 public 提交时间；缺少可靠修改时间时为空，前端明确降级为最近录入时间。actions_url 从无凭据的 GitHub HTTPS origin 构造，否则为空；前端只接受 GitHub 的 Actions 页面或运行链接，不接受任意业务 URL。

前端筛选以项目为单位：分类、当前状态、历史全文搜索共同确定项目集合，时间轴显示集合内的全部历史。日期精度仍显示原精度；同日时点与未知时间组不宣称相对先后。项目历史只包含当前有效公开版本，不包含本地修订 diff。

手动记录生成 draft-v1：稳定 draft_id、source:null、revision:null、默认 verification:needs_review，省略工具拥有的 record_id/recorded_at。同一条输入重复下载保留 ID，另记一条才重置；下载后不能直接切换项目。时间精度切换清空时间输入，避免把未知时刻误填为零点。手动确认的核实状态不等于批准发布。输入不持久化到浏览器存储，复制/下载是用户显式操作，回退文本始终可选取。

## 第三阶段 Git 事务

发布实现见 dashboard/publish.py、初始化见 dashboard/initialize.py。CLI 为 `publish.py --batch ID [--recover-only]`、`initialize.py local-init / prepare / bootstrap`。两者仅接受规范绝对路径的本地 bare 目标；初始化回执 mode 固定 local-bare-test，github_verified 和 pages_verified 均为 false。网络协议被禁用，不把本地演练视为 GitHub 或 Pages 的验收。

本地目录锁和 Git 目录锁串行化本工具操作。prepared 日志保存审批文件字节哈希、清单哈希、基准和事件；原文件备份先落盘。候选逐文件原子替换，暂存集合精确等于操作集合，验证 blob 和普通文件模式后使用 commit-tree 固定已核验树；update-ref 用原 HEAD 作比较，防止并发分支变动被覆盖。提交身份显式使用 noreply，时间固定为冻结批次时间，使提交对象创建可以幂等重试。commit_ready 在更新分支前保存提交对象 ID。

恢复状态为 prepared → rolled_back，或 commit_ready → committed → pushed / push_pending。已提交恢复验证唯一父提交、Progress-Batch 行、文件集合、blob 内容及模式；不只靠提交信息。日志丢失但 HEAD 为可核验的本批次提交时可重建日志。任意外部 HEAD 变动、不匹配文件或暂存内容均停止；不自动改变其他工作。

普通 push 不强推，之前查询远程，之后再次确认包含关系；结果不明保留提交，下一次重复查询。远程包含该提交或其后代则认定已送达；远程分叉停止。--recover-only 不推送，也可在远程暂时不可用时验证本地恢复。本地信任模型检测意外修改，不抵御具有同一账户文件写权限的恶意篡改。

## 后续外部部署约束

Git 发布必须具备本地锁、写前日志、旧文件备份和独立 prepared/committed/pushed 状态；提交前恢复仅接触匹配本批次哈希的文件。提交后不自动 reset。恢复用父提交、Progress-Batch trailer、文件集合及 blob 哈希共同定位；网络中断先查询远程。

初始化必须核实账户、公开属性和远程为空，再 bootstrap main；先部署代码和空数据站点，之后启用正常批准发布。不得自动合并远程自动生成 README 的独立历史。

后续 Pages 工作流只有 main push/main 手动运行可部署，PR 只检查；部署依赖检查和构建成功，environment 限 main，最小 pages/id-token 权限、SHA 固定、queue:max、旧提交重放保护。源码和公开数据只有一个 build.py 入口。
