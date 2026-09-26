# C3 / C4 代码专项题独立审查

审查日期：2026-09-26。对外已统一编号为C3（CrashKV）和C4（缓存一致性），原始归档仅用于内部来源审计。本次审查只写适配副本和本报告，未修改imports/pro_v01/upstream中的原件。

## 结论

两题可作为12题总集内的机制专项题加入；已有C1/C2承担完整服务仓库排障。两题的难点分别是崩溃恢复/耐久性边界、缓存身份/输入依赖语义，不能以大量小断言冒充大型工程复杂度。当前只有机制自测与原始计时；完整性能权重和资源profile未冻结，raw_score应保持null，不进入需要完整质量分的正式榜单。

## 执行安全与规则适配

执行前已逐项阅读两题baseline/starter和organizer/c1.py、c2.py、run_core.py。当前已知代码只使用标准库：本地文件、fcntl锁、临时目录和明确参数的Python子进程；无网络、凭据读取、动态下载、shell=True或宿主清理命令。裁判的写文件和SIGKILL只针对其创建的临时工作目录/子进程。此结论限于所审代码，同进程动态导入仍不是不可信提交安全沙箱。

C3的fsync调用与原子rename可从代码核对，但本次只做进程故障/注入异常，未断电、未控制磁盘缓存或文件系统设备。临时目录吞吐不能推广为真实掉电安全TPS。C4缓存可重建，发布原子性和校验保护不等同于权威数据耐久性；缺少目录fsync不应被误报为其当前合同的丢数据漏洞。

PUBLIC_TASK.md从原contestant题面派生，已改C3/C4对外编号并补齐异常/路径/故障接口，未包含基线算法、基线成绩或主办方实现。C4移除了未声明stats字段形成的隐含资格门槛：现在重复构建只检验结果，stats不参与资格或性能分。两份PUBLIC_TASK可与starter导出，组织者原TASK含解题线索不适合直接导出。

## 已证实并修复的问题

| 题目 | 实际复现 | 修复与证据 |
|---|---|---|
| C3 | compact原子replace之后，目录fsync失败；继续commit返回成功却写进已unlink旧WAL，重开丢确认数据 | I/O失败后句柄进入需关闭重开的失败状态，禁止新确认；独立注入测试由FAIL转PASS |
| C3 | WAL只写部分字节后异常，继续提交在损坏尾部之后追加；重开时丢掉之后已确认数据 | commit写入/同步/发布异常后同样失败封闭；独立测试FAIL转PASS |
| C3 | Store使用相对路径，调用者chdir后compact无法找到原目录 | 打开时固定绝对目录，独立测试ERROR转PASS |
| C3裁判 | 声称多进程锁但原single_writer仅同进程；READY.readline可能无限阻塞；杀进程异常路径缺回收 | 新增真正子进程争锁；READY用POSIX select设置5秒上限；finally回收；如果收到ACK，bulk必须全部恢复 |
| C4 | 非UTF8源送入upper时抛UnicodeDecodeError，未遵守新明确的BuildError接口 | 文本算子统一转换BuildError，独立测试ERROR转PASS |
| C4 | Builder保留relative cache；调用者chdir后缓存定位漂移并报FileNotFoundError | 构造时固定cache路径，独立测试ERROR转PASS |
| C4裁判 | warm命中检查信任未公开stats；并发子进程中一个失败可能漏回收其余进程 | 删除stats资格断言；并发批次finally逐个终止/回收；支持starter的同目录导入，并在子进程动态导入前注册sys.modules以兼容dataclass等合法实现 |

初筛怀疑的“JSON列表或坏UTF8缓存漏异常”未得到证实：原代码的ValueError/TypeError捕获已覆盖它们，本报告不把它计为bug。坏/不完整缓存重算现在作为公开回归补充。

## 本次真实运行结果

以下来自本次新执行日志，不是上游压缩包内自称成绩：

| 状态 | C3 baseline | C3 starter | C4 baseline | C4 starter |
|---|---:|---:|---:|---:|
| 修订前原机制裁判 | 10/10 | 5/10 | 14/14 | 1/14 |
| 修订后机制裁判 | 12/12 | 6/12 | 17/17 | 1/17 |

C3新独立故障注入回归原来2 FAIL+1 ERROR，修后3/3。C4新独立回归原来2 ERROR、1通过，修后3/3。原始红绿输出分别保存在各题review_runs/regressions_before.log、regressions_after.log，机制运行完整输出在before/after_baseline.log和before/after_starter.log，JSON另存并带当前环境信息。provenance.json记录原始来源摘要，after JSON记录当前baseline摘要。

修订后本机四次机制评测各约0.261/0.303/0.137/0.062秒，仅是小profile。C3只有200次随机事务、4次强杀时窗、500次单事务计时；C4主体是4节点DAG、100次变更、6进程发布。10万键、8读者、256MiB、数千故障、5000节点、数百MiB均未执行。不能以高难档设计值为本次实测规模。

## 难度和剩余边界

建议定位：C3是中高难度存储安全机制题（组合I/O错误可暴露“表面全绿”后的数据丢失）；C4是中等难度缓存一致性题（隐含身份、路径、编码与可达性），需多模型试跑才能量化前沿模型难度。不能预先承诺难倒某个模型。

C3基线仍采用有限单帧大小，巨量状态/长幂等历史会限制压缩容量；当前小profile没有验证其极限，不应把它当成全容量唯一正确实现。C4采用递归解释与每次读取源，极深DAG和大输入下的资源行为未验证。当前输入树在一次build期间保持稳定，所以没有解决源文件/符号链接被恶意并发替换的TOCTOU问题；缓存假设为可损坏但非恶意宿主伪造的可重建数据。上述范围在公开题面明确。

性能质量函数、P99、内存、恢复时间/缓存膨胀等完整项目仍缺固定profile，故本次不制造数值总分。命中率也不是正确性证明，不能用自报stats替代外部性能观测。

## 运行与迁移

当前路径下运行：

```sh
python3 -B code/C3/review_run.py --implementation baseline
python3 -B code/C3/review_run.py --implementation starter
python3 -B code/C4/review_run.py --implementation baseline
python3 -B code/C4/review_run.py --implementation starter
```

分别进入题目录执行python3 -B -m unittest -v test_review.py可重跑新增独立回归。

合并时可把任务目录迁至code/C3和code/C4；organizer/c1.py、c2.py是自包含evaluate(mod)，分别复制为新题目录evaluator.py即可。review_run.py优先读本目录evaluator.py，也接受--evaluator；候选模块就地发现，不再依赖ROOT/tasks。C3/C4的PUBLIC_TASK为参赛导出入口，baseline/test_review/review_runs仍是组织者资料，不能混入参赛包。
