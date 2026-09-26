"""Rebuild the fixed synthetic frontend fixtures and standalone baseline pages."""
from pathlib import Path
import json

ROOT = Path(__file__).parent
services = ['gateway', 'checkout', 'inventory', 'payments', 'identity', 'search', 'worker', 'database']
titles = ['连接池等待超过阈值', '队列消费延迟升高', '读取副本超时', '重试放大流量', '熔断器打开', '恢复探针通过', 'CPU 配额触顶', '下游依赖不可达']
events = []
for i in range(10000):
    sec = 3 * 3600 + 14 * 60 - i
    cluster = i // 5
    events.append({'id': f'EVT-{i+1:05}', 'time': f'{sec//3600:02}:{sec//60%60:02}:{sec%60:02}',
      'severity': ['P1','P2','P2','P3','P3'][i%5], 'service': services[(i * 13 + i//17)%8],
      'title': titles[(i*7+i//23)%8], 'trace': f'TR-{cluster:04}',
      'parent': None if i%5==0 else f'EVT-{i:05}', 'source': '仿真注入链',
      'detail': f'固定合成事件 {i+1}。租户 {i%37:02}，分片 {i%16:02}。观测窗口内错误率 {((i*19)%850)/10:.1f}%，p99 延迟 {80+(i*37)%6200} ms。证据来源为合成回放；相邻时间不能单独证明因果。' + ('\n长文本测试：' + '重试请求等待连接释放；下游已收到相同幂等键。'*40 if i%97==0 else '')})
special = [
 ('database','P1','主库连接上限从 400 误设为 40',None),
 ('inventory','P1','库存写入等待连接池','EVT-00001'),
 ('checkout','P1','结算超时触发无退避重试','EVT-00002'),
 ('gateway','P1','入口请求堆积，错误率达到 38%','EVT-00003'),
 ('payments','P2','回调延迟，支付记录未丢失','EVT-00003'),
 ('worker','P2','重复重试挤占后台任务','EVT-00003')]
for i,(service,sev,title,parent) in enumerate(special):
    events[i].update(service=service,severity=sev,title=title,parent=parent,trace='TR-INCIDENT-042',time=f'03:12:{i*9:02}')
events[6]['parent'] = None
events[42]['title'] = '字面量测试 <img src=x onerror="window.fixtureInjected=true">'
(ROOT/'F1'/'data.json').write_text(json.dumps({'schema':1,'synthetic':True,'fixture':'night-shift-10000-v1','events':events}, ensure_ascii=False, separators=(',',':')))
for task in ['F1','F2']:
    source = (ROOT/task/'baseline.template.html').read_text()
    payload = json.loads((ROOT/task/'data.json').read_text())
    (ROOT/task/'baseline.html').write_text(source.replace('__FIXTURE__',json.dumps(payload,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')))
    starter = ROOT/task/'starter.template.html'
    if starter.exists():
        (ROOT/task/'starter.html').write_text(starter.read_text().replace('__FIXTURE__',json.dumps(payload,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')))
