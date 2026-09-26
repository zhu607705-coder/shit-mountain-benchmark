"""Pilot browser checks. Run against the bundled baseline, not a secure submission grader."""
from __future__ import annotations
import functools,http.server,json,threading,time,statistics,os,shutil
from pathlib import Path
from playwright.sync_api import sync_playwright
from memory_browser import MemoryBrowser
ROOT=Path(__file__).resolve().parents[1]

def main():
    handler=functools.partial(http.server.SimpleHTTPRequestHandler,directory=str(ROOT))
    class Quiet(handler.func):
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(ROOT)))
    threading.Thread(target=server.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{server.server_port}'
    with sync_playwright() as p:
        exe=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium')
        browser=p.chromium.launch(**({'executable_path':exe} if exe else {}),headless=True,args=['--no-sandbox'])
        for task in os.environ.get('UI_TASKS','F1,F2').split(','):
            context=browser.new_context(viewport={'width':1440,'height':1050},accept_downloads=True)
            memory=MemoryBrowser(context)
            page=context.new_page();page.set_default_timeout(3000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)));checks=[]
            def check(name,fn):
                print('CHECK',task,name,flush=True)
                try:fn();checks.append({'name':name,'pass':True})
                except Exception as e:checks.append({'name':name,'pass':False,'error':str(e)[:800]});print('FAIL',name,str(e)[:200],flush=True)
            def wait():page.wait_for_timeout(90);memory.flush()
            def eq(a,b):
                if a!=b:raise AssertionError(f'{a!r} != {b!r}')
            if task=='F1':
                link=url+'/tasks/F1_incident_console/baseline.html';memory.load(page,(ROOT/link.split(url+'/')[1]).read_text(),link);page.wait_for_function("document.querySelector('#count').textContent.includes('50,000')")
                check('50k_records',lambda:eq(page.locator('#count').inner_text(),'50,000 / 50,000 条记录'))
                check('bounded_dom',lambda:eq(page.locator('.row').count()<50,True))
                page.screenshot(path=str(ROOT/'results/F1_desktop.png'),full_page=True)
                def search():
                    page.get_by_label('搜索标题或服务').fill('12345');wait();eq(page.locator('.row').count(),1);page.locator('.row').click();eq(page.locator('#detail-body').inner_text().find('INC-12345')>=0,True)
                check('search_and_select',search)
                def stable():
                    page.evaluate("bench.ingest([{id:'INC-12345',rev:2,title:'12345 已更新',service:'gateway',severity:0,status:'open',updated:1999999999999}])");wait();eq(page.locator('#detail-title').inner_text(),'12345 已更新')
                    page.evaluate("bench.ingest([{id:'INC-12345',rev:1,title:'OLD 12345',service:'gateway',severity:3,status:'open',updated:2999999999999}])");wait();eq(page.locator('#detail-title').inner_text(),'12345 已更新')
                check('stable_id_and_stale_rejection',stable)
                def paused():
                    page.get_by_role('button',name='暂停更新',exact=True).click();page.evaluate("bench.ingest([{id:'INC-12345',rev:3,title:'12345 暂停后的版本',service:'gateway',severity:1,status:'open',updated:1999999999999}])");wait();eq(page.locator('#detail-title').inner_text(),'12345 已更新');page.get_by_role('button',name='恢复更新',exact=True).click();wait();eq(page.locator('#detail-title').inner_text(),'12345 暂停后的版本')
                check('pause_resume',paused)
                def tombstone():
                    page.evaluate("bench.ingest([{id:'INC-12345',rev:4,deleted:true}])");wait();eq(page.locator('.row').count(),0);eq(page.locator('#detail-title').inner_text(),'选择一条事故记录')
                    page.evaluate("bench.ingest([{id:'INC-12345',rev:2,title:'12345 resurrect',service:'g',severity:0,status:'open',updated:1}])");wait();eq(page.locator('.row').count(),0)
                check('tombstone_no_resurrection',tombstone)
                def safe():
                    page.locator('#search').fill('');page.evaluate("bench.load([{id:'attack',rev:1,title:'=1+2<img src=x onerror=alert(1)>',service:'test',severity:0,status:'open',updated:1730000000000}])");wait();eq(page.locator('#rows img').count(),0);eq('<img' in page.locator('.row-title').inner_text(),True)
                check('untrusted_title_is_text',safe)
                def csv():
                    page.get_by_role('button',name='导出筛选结果').click()
                    text=page.evaluate('window.__lastBlob.text()');eq("'=1+2<img" in text,True)
                check('csv_formula_neutralization',csv)
                def keys():
                    page.evaluate("bench.load([{id:'a',rev:1,title:'A',service:'s',severity:0,status:'open',updated:2},{id:'b',rev:1,title:'B',service:'s',severity:1,status:'open',updated:1}])");wait();page.locator('#viewport').focus();page.keyboard.press('ArrowDown');wait();eq(page.locator('#detail-title').inner_text(),'A');page.keyboard.press('ArrowDown');wait();eq(page.locator('#detail-title').inner_text(),'B')
                check('keyboard_selection',keys)
                def reload_url():
                    page.locator('#search').fill('queue');wait();memory.reload(page,(ROOT/link.split(url+'/')[1]).read_text());wait();eq(page.locator('#search').input_value(),'queue');eq('q=queue' in page.evaluate('window.__test_url'),True)
                check('url_filter_reload',reload_url)
                page.locator('#search').fill('');wait()
                timings=[]
                for i in range(12):
                    elapsed=page.evaluate("""async i=>{const a=performance.now();bench.ingest(Array.from({length:200},(_,j)=>({id:'INC-'+String(j).padStart(5,'0'),rev:i+10,title:'Latency '+j,service:'gateway',severity:j%4,status:'open',updated:1999999999000+i*200+j})));await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));return performance.now()-a;}""",i);timings.append(elapsed)
                extras={'batch_200_to_two_animation_frames_ms_median':statistics.median(timings),'batch_200_to_two_animation_frames_ms_p95':sorted(timings)[-1],'dom_rows':page.locator('.row').count()}
            else:
                link=url+'/tasks/F2_offline_planner/baseline.html';memory.load(page,(ROOT/link.split(url+'/')[1]).read_text(),link);wait();page.screenshot(path=str(ROOT/'results/F2_desktop.png'),full_page=True)
                check('initial_12_tasks',lambda:eq(page.locator('.task').count(),12))
                def select(pg,id):pg.locator('.task[data-id="'+id+'"]').click()
                def save(pg):pg.get_by_role('button',name='保存修改',exact=True).click();pg.wait_for_timeout(90);memory.flush()
                def edit():
                    select(page,'TASK-000');page.get_by_label('任务标题').fill('本地编辑 <img src=x>');save(page);eq(page.locator('.task[data-id="TASK-000"] .task-title').inner_text(),'本地编辑 <img src=x>');eq(page.locator('.task img').count(),0)
                check('edit_and_safe_text',edit)
                def undo_redo():
                    page.get_by_role('button',name='撤销',exact=True).click();wait();eq(page.locator('.task[data-id="TASK-000"] .task-title').inner_text(),'数据核验与异常记录');page.get_by_role('button',name='重做',exact=True).click();wait();eq(page.locator('.task[data-id="TASK-000"] .task-title').inner_text(),'本地编辑 <img src=x>')
                check('undo_redo',undo_redo)
                def invalid_range():
                    select(page,'TASK-001');page.get_by_label('开始时间').fill('15:00');page.get_by_label('结束时间').fill('14:00');save(page);eq('确保结束时间晚于开始时间' in page.locator('#message').inner_text(),True);page.get_by_role('button',name='重新载入',exact=True).click()
                check('invalid_range_rejected',invalid_range)
                p2=context.new_page();p2.set_default_timeout(3000);memory.load(p2,(ROOT/link.split(url+'/')[1]).read_text(),link);p2.wait_for_timeout(100)
                def merge():
                    select(page,'TASK-002');select(p2,'TASK-002');page.get_by_label('任务标题').fill('窗口一的标题');save(page);p2.get_by_label('备注',exact=True).fill('窗口二的备注');save(p2);page.get_by_role('button',name='重新载入',exact=True).click();wait();eq(page.get_by_label('任务标题').input_value(),'窗口一的标题');eq(page.get_by_label('备注',exact=True).input_value(),'窗口二的备注')
                check('two_window_disjoint_field_merge',merge)
                def conflict():
                    select(page,'TASK-003');select(p2,'TASK-003');page.get_by_label('任务标题').fill('远端更新优先');save(page);p2.get_by_label('任务标题').fill('旧编辑器覆盖');save(p2);eq('编辑冲突' in p2.locator('#message').inner_text(),True)
                check('stale_form_conflict',conflict)
                def offline():
                    page.get_by_role('button',name='切换离线',exact=True).click();p2.get_by_role('button',name='切换离线',exact=True).click();select(page,'TASK-004');select(p2,'TASK-004');page.get_by_label('备注',exact=True).fill('离线备注');save(page);p2.get_by_label('任务标题').fill('离线标题');save(p2);page.get_by_role('button',name='恢复在线',exact=True).click();p2.get_by_role('button',name='恢复在线',exact=True).click();wait();page.get_by_role('button',name='重新载入',exact=True).click();wait();eq(page.get_by_label('任务标题').input_value(),'离线标题');eq(page.get_by_label('备注',exact=True).input_value(),'离线备注')
                check('offline_merge',offline)
                def remote_undo():
                    select(page,'TASK-005');page.get_by_label('任务标题').fill('local');save(page);select(p2,'TASK-005');p2.get_by_label('任务标题').fill('remote');save(p2);page.get_by_role('button',name='撤销',exact=True).click();wait();eq('撤销冲突' in page.locator('#message').inner_text(),True);eq(page.locator('.task[data-id="TASK-005"] .task-title').inner_text(),'remote')
                check('undo_does_not_overwrite_remote',remote_undo)
                def duplicates():
                    page.evaluate('bench.importDocument(bench.exportDocument())');wait();eq(page.locator('.task').count(),12)
                check('duplicate_import_idempotency',duplicates)
                def keyboard():
                    select(page,'TASK-006');page.get_by_label('工作站',exact=True).select_option('2');save(page);eq(page.locator('#lane-2 .task[data-id="TASK-006"]').count(),1)
                check('keyboard_alternative_to_drag',keyboard)
                def remove():
                    select(page,'TASK-007');page.once('dialog',lambda d:d.accept());page.get_by_role('button',name='删除任务',exact=True).click();wait();eq(page.locator('.task').count(),11);eq(p2.locator('.task').count(),11)
                    page.evaluate("bench.importDocument({version:1,events:[{id:'late-update',actor:'z',clock:999,item:'TASK-007',kind:'patch',fields:{title:'不应复活'}}]})");wait();eq(page.locator('.task[data-id="TASK-007"]').count(),0)
                check('delete_tombstone_late_patch',remove)
                def export():
                    page.get_by_role('button',name='导出',exact=True).click()
                    data=json.loads(page.evaluate('window.__lastBlob.text()'));eq(data['version'],1);eq(len(data['events'])>=12,True)
                check('exported_document',export)
                def reload():
                    memory.reload(page,(ROOT/link.split(url+'/')[1]).read_text());wait();eq(page.locator('.task').count(),11);eq(page.locator('.task[data-id="TASK-002"] .task-title').inner_text(),'窗口一的标题')
                check('persistent_reload',reload)
                extras={'notes':'No subjective design score or full accessibility conformance asserted.'};p2.close()
            for width in (320,768):
                def reflow(width=width):
                    page.set_viewport_size({'width':width,'height':1000});wait();eq(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),True);page.screenshot(path=str(ROOT/f'results/{task}_{width}.png'),full_page=True)
                check(f'reflow_{width}px',reflow)
            check('no_browser_uncaught_errors',lambda:eq(errors,[]))
            result={'environment':'about:blank DOM + explicit memory storage/navigation/download adapter; NOT native-origin e2e', 'checks_passed':sum(x['pass'] for x in checks),'checks_total':len(checks),'checks':checks,'browser':browser.version,'measurements':extras}
            (ROOT/f'results/{task}_baseline.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(task,json.dumps(result,ensure_ascii=False),flush=True);context.close()
        browser.close()
    server.shutdown()
if __name__=='__main__':main()
