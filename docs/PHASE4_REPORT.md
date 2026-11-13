# 第四阶段：GitHub Pages 空站验收

日期：2026-11-13。公开仓库与首次空数据站点已上线，未发布真实进度。非空业务数据仍由生产工作流强制阻止。

- [线上看板](https://ychris12138.github.io/progress-dashboard/)
- [公开仓库](https://github.com/Ychris12138/progress-dashboard)
- [Pages 工作流](https://github.com/Ychris12138/progress-dashboard/actions/workflows/pages.yml)

## 身份与初始化

GitHub 连接器与本地 gh 均确认账户为 Ychris12138。目标仓库创建前不存在；创建后核对公开属性、默认分支 main，以及账户 admin/push 权限。仅提交审核过的源码、文档、合成 tests/fixtures 和空 public；私有草稿、来源缓存、审批及真实 PoC 证据没有进入仓库。

本机 Git HTTPS 端点连接超时，SSH 443 的现有密钥未获授权，未修改凭据或主机信任。使用可用的 GitHub API，在独立 bootstrap-seed 分支建立只含审核 README 的引导提交，再重建本地完整 Git tree 与根提交。两端 tree SHA 和 commit SHA 完全一致，main 初始提交为 `beb3f033fc842d4693cabe946dfaf1f30b00e7bd`。未强推、未改写本地提交；后续更新核对父提交并仅做快进。

## 实际验收

| 场景 | 观察到的结果 |
|---|---|
| 首次空站部署 | Python 3.12／3.14、前端、构建和部署全部成功 |
| PR | 检查成功，build/deploy 均跳过；验收 PR 已关闭且未合并 |
| 非 main 手动运行 | 检查成功，build/deploy 均跳过 |
| main 故意构建失败 | build 失败，deploy 跳过；原站五个资源的 SHA-256 全部不变 |
| 旧成功运行重放 | guard 拒绝过期提交，Deploy checked empty site 步骤跳过；线上五个资源哈希不变 |
| 线上数据 | projects 与 timeline 均为空，synthetic=false；资源可从项目子路径加载 |
| 手机 360px／390px | 独立 Chromium 实测通过，页面无横向溢出；原生弹窗和合成 JSON 下载正常 |
| 浏览器脚本与写请求 | 两个手机视口均为 0 页面错误、0 写入请求 |

本地 Python 3.12.14：85 项测试通过；GitHub 的 Python 3.12／3.14 矩阵也实际通过。前端 29 项 DOM 测试通过。线上手机浏览器另有 2 项完整交互测试通过。

运行证据：

- [首次部署与旧运行重放](https://github.com/Ychris12138/progress-dashboard/actions/runs/43359610482)（首次为 attempt 1；重放为 attempt 2，重放不部署）
- [PR 检查](https://github.com/Ychris12138/progress-dashboard/actions/runs/43359880005)
- [非主分支手动运行](https://github.com/Ychris12138/progress-dashboard/actions/runs/43359899949)
- [预期失败的构建保护测试](https://github.com/Ychris12138/progress-dashboard/actions/runs/43359905229)
- [后续正常部署](https://github.com/Ychris12138/progress-dashboard/actions/runs/43360501040)
- [Chromium 手机验收](https://github.com/Ychris12138/progress-dashboard/actions/runs/43360517060)

## 权限与失败保护

仓库 Actions 默认 token 权限为 read，仅允许 GitHub 官方 Actions。工作流全局权限为空，按 job 分配：检查只读 contents；build 只读 contents/pages；仅 deploy 获取 pages:write、id-token:write，并只读 deployments 历史。

github-pages Environment 读回确认只有名称为 main 的 branch 规则，没有 tag 规则。PR 与非主分支不会进入部署；构建失败也不会执行部署。Actions 均固定完整 SHA。queue:max 不取消运行中的工作流，按进入等待队列的顺序处理，不宣称按提交时间排序。

部署前读取最新 main 与成功部署历史，拒绝旧提交和分叉历史，API 检查失败时停止。源码和正式产物只有一个 build.py 构建入口；发布产物仅为五个站点运行文件，不包含 tests、私有状态或源码目录。

## 手机视觉与快捷入口

本机 CUA 曾成功发现浏览器，但打开 Chrome、内置浏览器及原生应用时均超时。因此实际手机验收改在 GitHub 托管 Linux 中使用独立 Chromium，没有从本机 shell 启动系统 Chrome，也未更改其个人配置。

已取回并检查首页和记录弹窗截图：360px 页面 scrollWidth=360，390px 页面 scrollWidth=390；弹窗宽分别为 322 和 352px，均在视口内。文字正常显示，筛选控件、空状态与记录按钮可见。测试生成的草稿均为固定合成内容，保持 needs_review，没有上传业务数据。

这是 Chromium 的手机尺寸视口验证，不是实体 iPhone／Android 或 Safari 验证。截图、metrics 与完整运行结果保存在项目同级私有目录的 reports/phase4/。其中含少量合成测试输入，不纳入 Pages。

已生成 `.webloc`，URL 固定指向最终 HTTPS 站点；文件位于同级私有目录的 shortcuts/个人进度看板.webloc，可复制到桌面。

## 尚未启用

真实进度的网络发布没有启用。第三阶段 publish.py 仍只接受本地 bare 目标，Pages 的空数据检查也继续生效。未来启用真实数据时，需要明确授权、通过批次审批，并单独调整网络发布与非空部署门槛，不能复用合成演练的自动批准逻辑。

更多配置依据与故障说明见 [PAGES.md](PAGES.md)。
