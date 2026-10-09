"""Vendor only the Lucide SVG icons used by the no-build interface."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen
import re

root = Path(__file__).resolve().parents[1]
names = {
 'grid_view':'layout-dashboard','manage_accounts':'users','rocket_launch':'rocket','filter_alt':'list-filter',
 'forum':'messages-square','precision_manufacturing':'workflow','schedule':'calendar-clock','receipt_long':'scroll-text',
 'tune':'sliders-horizontal','person':'user','menu':'menu','search':'search','play_arrow':'play','notifications':'bell',
 'close':'x','refresh':'refresh-cw','add':'plus','save':'save','upload':'upload','download':'download','delete':'trash-2',
 'edit':'pencil','person_add':'user-plus','send':'send','cached':'repeat-2','mark_email_read':'mail-check',
 'playlist_add_check':'list-check','schedule_send':'send','info':'info','check_circle':'circle-check',
 'warning':'triangle-alert','error':'circle-alert','verified_user':'shield-check','arrow_forward':'arrow-right',
 'arrow_back':'arrow-left','chevron_left':'chevron-left','chevron_right':'chevron-right','expand_more':'chevron-down',
 'expand_less':'chevron-up','open_in_full':'maximize-2','vertical_align_bottom':'arrow-down-to-line','pause':'pause',
 'check':'check','logout':'log-out','sync':'refresh-cw','more_horiz':'ellipsis','more_vert':'ellipsis-vertical',
 'mail':'mail','email':'mail','link':'link','open_in_new':'external-link','content_copy':'copy','visibility':'eye',
 'analytics':'chart-no-axes-combined','leaderboard':'chart-column','settings':'settings','bolt':'zap',
 'smart_toy':'bot','checklist':'list-check','upload_file':'file-up','file_download':'file-down',
 'calendar_today':'calendar','timer':'timer','history':'history','task_alt':'circle-check','person_off':'user-x',
 'sort':'arrow-down-wide-narrow','filter_list':'list-filter','comment':'message-square','chat':'message-circle',
 'thumb_up':'thumbs-up','thumb_down':'thumbs-down','done':'check','done_all':'check-check','help':'circle-help',
 'arrow_upward':'arrow-up','arrow_downward':'arrow-down','calendar_month':'calendar-days',
 'filter_alt_off':'list-restart','shield':'shield','dns':'server','cloud_done':'cloud','lock':'lock-keyhole',
 'autorenew':'refresh-cw','date_range':'calendar-range','unfold_more':'chevrons-up-down'
}
base = 'https://raw.githubusercontent.com/lucide-icons/lucide/0.468.0/'
def fetch(name):
    try:
        with urlopen(base+'icons/'+name+'.svg', timeout=30) as response:
            return name, response.read().decode()
    except Exception as error:
        print('Failed icon:', name, error, flush=True)
        return name, None
with ThreadPoolExecutor(max_workers=8) as pool:
    icons = dict(pool.map(fetch, sorted(set(names.values()))))
assert all(icons.values()), 'Resolve unavailable icon names before building'
symbols = []
for key, name in names.items():
    inner = re.sub(r'^.*?<svg\b[^>]*>', '', icons[name], flags=re.S).rsplit('</svg>',1)[0]
    symbols.append(f'<symbol id="{key}" viewBox="0 0 24 24">{inner}</symbol>')
(root/'static'/'icons.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg">'+''.join(symbols)+'</svg>',encoding='utf-8')
(root/'static'/'LUCIDE-LICENSE.txt').write_bytes(urlopen(base+'LICENSE',timeout=30).read())
print(f'Vendored {len(names)} icon aliases; '+str((root/'static'/'icons.svg').stat().st_size)+' bytes')


