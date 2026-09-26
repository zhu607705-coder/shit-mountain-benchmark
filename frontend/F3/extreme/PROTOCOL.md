# 公开语义适配协议 v2

本协议规定可观察状态，不指定框架、DOM class、信息架构或冲突对话框布局。提交的 UI 与 adapter 必须调用同一个状态引擎。独立写一个只会答 fixture 的 adapter 不构成前端完成；组织者应核查模块归属并执行浏览器工作流。

## 运行和输出

提供 `adapter.py`、`adapter.cjs` 或 `adapter.js`。进程从 stdin 逐行读取 JSON，每个命令向 stdout 恰好写一行 JSON。日志写 stderr。操作返回 `{"ok":true}`；公开规定的非法原子批次返回 `{"ok":false,"error":"可理解的原因"}`。只要命令响应或记录未经执行，不能把它计为完成。扩展响应字段允许存在，公开字段类型与语义必须一致。整数不能用布尔值替代。

`config` 提供 task、actors、schema=2、protocol=`smb.frontend.extreme/2`。`load` 分批追加初始记录；配置后到第一次操作前的所有 load 合成同一初始文档。load 中 ID 唯一。F1/F3 使用共享事件事实源与每窗口独立视图；F2/F4 每 actor 的文档从相同 load 初态开始，只接收显式 deliver 给它的事件。

`observe` 提供 actor、ids；响应为 `ok,count,records` 以及下面适用的状态。records 是以所请求 ID 为键的对象，缺失/已删除/旧别名返回 null。返回完整公开记录，不把内部版本或 UI 状态塞进记录字段。F1/F3 count 是当前窗口可见快照的全部活记录数；F2/F4 是该副本活任务总数。实际筛选结果在 UI 中另外验证。

`export` 响应必须包含真实全量 `rows` 数组，不能只返回计数或自己声称的 hash。裁判独立检查数量、重复 ID 和规范化所有行后的 SHA-256。行顺序不影响结果：按 ID 的 Unicode 码点排序，行内 JSON key 排序，UTF-8、无多余空格、每行末尾一个 LF。全部公开行字段均参与校验。

## F1/F3 记录与流

记录是 `{id,generation,rev,title,service,severity,status}`。本版初始 generation=0、rev=1；severity 0–3。`ingest` 的 rows 是完整 upsert 记录或 `{id,generation,rev,deleted:true}`。同一规范身份/世代只接受更高 rev；重复/迟到输入不能覆盖当前事实。stream 和 seq 描述传输来源与光标，不得代替记录修订号。

F1 `alias {old,canonical,proof,seq}` 是已由服务端确认的身份映射，不是从时间邻近推测根因。规范身份沿链更新；选择、焦点、历史 URL 引用、确认集合与后续旧别名输入都必须归一化。同一身份只占一条记录。来自旧别名的高版本会更新规范记录；低版本不能覆盖新事实。observe 的 selection/focus 是规范 ID。

F1 `ack {actor,id,value,dot,observed}` 使用 observed-remove 语义：value=true 添加唯一 dot，false 仅移除 observed 中的添加 dot，不移除尚未被本次操作观察到的并发确认。actor 本身不能充当最终版本。observe 的 acked 为规范 ID 的升序数组。

F1 `view {actor,selection,focus,filter,push}` 更新视图；push=true 将 selection/filter 作为新历史项并截断前向历史。`history {actor,delta}` 按 -1/+1 后退/前进，边界不越界；恢复时重新解析别名。焦点只由显式 view 或身份映射改变，后台更新不能抢焦点。`stream {stream,connected,last_seq}` 记录局部可用性；observe 的 stale_streams 返回 disconnected 的来源升序数组，不得把一条流断连解释成全部事实消失。

F3 `pause {actor,value,snapshot?}`：暂停创建该窗口不可变 cut，其他窗口可继续实时查看。observe 与 export 都读取该窗口同一 cut；恢复回到最新可见事实。不限定用复制、MVCC、持久化结构或日志重放实现。

F3 `compact {epoch,watermarks,floor}`：watermarks 是各活跃来源已确认的修订前沿。落后来源存在时不能忘记防复活知识。floor=0 不提供全局回放屏障；floor>0 表示所有来源已共同确认不再合法产生 revision<=floor 的新事件，且该 epoch 成为持久化恢复屏障。压缩可以释放日志/墓碑载荷，但后续旧 epoch 或 revision<=floor 的回放不能恢复被删除记录。已有低版本活记录无需删除。公开用例只在所有 watermark>=floor 时提升 epoch。永久保留版本知识在语义层可行；是否满足内存与长时性能预算由真实浏览器测量，当前 runner 不伪造该结果。

## F2/F4 因果任务文档

任务记录为 `{id,generation,title,resource,start,end,deps,notes}`，start/end 使用整分钟、区间 `[start,end)`，resource 为非负整数、deps 为任务 ID 数组。公开数据没有秘密实验约束；任务是合成的排程对象。

`deliver {actor,events}` 是向指定副本递送完整批次。事件格式：`{id,actor,counter,context,item,generation,kind,fields?}`。id 唯一，counter 为该来源正整数逻辑序号，context 是已观察到的 actor→counter 向量。kind 为 patch/delete/restore。context 可涵盖在本地尚未收到的历史；不能仅因网络反序而丢弃当前事件。字段冲突判断按因果支配：事件 e 的 context[f.actor]>=f.counter 表示 e 观察到 f；同来源 counter 较大也表示因果后继。不同字段独立合并。因果后继的字段值淘汰被它观察到的旧值；同字段多个互不支配的最大候选保留冲突。展示值在剩余并发候选中按 `(counter, actor, id)` 最大项选择，字符串按 Unicode 码点比较。此显示规则不等于宣称它最符合用户意图，用户应看到备选值与来源。显式解决事件观察全部候选后可清除冲突。

observe 的 conflicts 是 `任务ID:字段名` 升序列表，仅包含当前未解决的因果并发；顺序远端改写不属于并发冲突。对合法输入做确定性投影不限制内部 CRDT/OT/数据库实现。

合并后可以暂存不合法排程，不能静默删除任务、重排时间或改写用户意图。observe 的 issues 是升序字符串数组：`range:ID` 表示 start>=end；`dependency:PREDECESSOR:CHILD` 表示前驱结束晚于子任务开始；`overlap:SMALL_ID:LARGE_ID` 表示同资源合法时间段相交。范围非法记录只报告 range，不再为该记录推导 overlap/dependency。未知依赖 `missing:CHILD:UNKNOWN`；自环或多点依赖环按每个参与 ID 报 `cycle:ID`。当前自动样本覆盖 range、overlap、dependency；环和未知依赖的 UI 修复流仍需验收。

`undo {actor,target,id,context}` 为条件补偿：只还原 target 修改且当前仍由 target 唯一决定的字段；若之后存在其他因果后继或并发候选，跳过该字段并提示原因，不得覆盖远端结果。先前值来自 target 的因果前态，不是提交时当前值。

F4 delete 为该 generation 的不可逆墓碑，高 counter 的旧 patch 也不能复活。同一 item 的 `restore` 必须带 `tombstone` 引用已观察到的删除事件，context 覆盖它，generation 必须恰为已删除世代+1，并提供完整任务 fields。这表示用户显式新建下一世代；旧世代消息全部隔离。普通撤销不能代替 restore。

整个 deliver 批次必须先验证再提交：同 ID 同内容为幂等；已有历史或同批内部出现同 ID 不同内容时整批拒绝，包括前面合法的事件。JSON key 顺序不改变内容。observe 的 event_count 是该副本已接受的不同事件 ID 数。

F2 `storage {actor,fail}` 是确定性持久化故障注入。失败期间编辑保留内存并报告 saved=false，不得显示已落盘。后续成功持久化必须包含待保存的全部当前文档。`refresh {actor}` 丢弃易失视图，从最后成功持久化状态恢复。无 durable copy 的编辑不能伪造恢复证明。

F2 `restore_document {actor,document}` 导入已有恢复副本。schema=1 的 rows 以 duration 替代 end，其单位仍为分钟；迁移为 schema=2，end=start+duration，其余字段与 pending 意图保留。迁移不得借机会重排任务。observe 返回当前 schema。

## 分数边界

本 runner 只发布每条语义性质是否通过及其等权比例。它不是最终前端质量分，不把基线得分定为100，也不以没提供旧作者 DOM 作为失败理由。整体 full 记录的生成、送入进程、应答和导出验证分别记录；不能推导浏览器已承受相同负载。正式轮需冻结新的输入种子/交错序列及权重，并在提交前公布本语义契约。当前全部公开轨迹属于开发/训练集，不能宣称抗污染隐藏题。
