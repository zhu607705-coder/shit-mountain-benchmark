# 修复诊断记录

修复前实跑命令：python3 -B e2e_env_judge.py --submission repository/buggy --output repository_buggy_result.json。环境2/7、核心10/63，原smoke测试正向通过但0/5变异检测，原分23.174603。

1. db.initialize只做CREATE IF NOT EXISTS并改user_version，旧表不会增加claimed_at或重建唯一键，worker实际报no such column: claimed_at。改为同一事务内重建jobs/events、复制数据、保留旧ID/状态，再提交版本。
2. 发现v1的带空白JSON会导致迁移后重放同一请求误报409。先添加旧请求重放断言，实际看到ServiceError: REQUEST_CONFLICT；再在迁移时解析并规范化payload，测试转绿。
3. config对相对路径直接resolve，API/worker cwd不同即各建一库。改为相对仓库目录解析，保留绝对/Unicode路径。
4. worker只领取pending，processing任务永久丢失进展。改为事务内领取pending或过期processing；完成时复查claimed_at令牌，过期旧领取者不能提交。
5. 查重SQL只有request_id，导致跨租户冲突。改为tenant/request_id联合条件，并保持同租户同键异载荷409。
6. 工作流成功仍可能由遗留engine生成错账。仓库内改为C1已验证的两阶段冲突隔离、集合撤销和整数投影；HTTP与核心裁判始终调用本仓库engine.py。

作者新增5项测试覆盖路径、租户请求/读取、混租户原子拒绝、迁移历史/旧重放、过期领取回收。HTTP backlog增至64，避免短并发被默认小队列干扰。

当前worker每次重算本租户全部事件，仍有吞吐优化空间。未验证真实身份认证、跨主机分区、磁盘损坏、无限数据增长和生产多副本部署。
