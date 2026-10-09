import sqlite3
import requests

print("=== LOCAL CAMPAIGNS TABLE ===")
con = sqlite3.connect("app_data/app_data.db")
cur = con.cursor()
cols = [description[0] for description in cur.execute("SELECT * FROM campaigns").description]
print("Columns:", cols)
local_campaigns = cur.execute("SELECT * FROM campaigns").fetchall()
for c in local_campaigns:
    print(c)

print("\n=== LOCAL LEAD COUNTS PER CAMPAIGN ===")
local_lead_counts = cur.execute("SELECT campaign_id, count(*) FROM leads GROUP BY campaign_id").fetchall()
for cid, cnt in local_lead_counts:
    cname = cur.execute("SELECT name FROM campaigns WHERE id=?", (cid,)).fetchone()
    cname_str = cname[0] if cname else "Unassigned/None"
    print(f"Campaign ID {cid} ({cname_str}): {cnt} leads")

print("\n=== LIVE CAMPAIGNS API RESPONSE ===")
s = requests.Session()
s.post('https://outreach-app-7zc5l7znlq-uc.a.run.app/api/login', json={'username': 'admin', 'password': 'Admin@_2026!'})
live_campaigns = s.get('https://outreach-app-7zc5l7znlq-uc.a.run.app/api/campaigns').json()
for lc in live_campaigns:
    print(lc)

print("\n=== LIVE CAMPAIGN STATS API RESPONSE ===")
for lc in live_campaigns:
    cid = lc['id']
    stats = s.get(f'https://outreach-app-7zc5l7znlq-uc.a.run.app/api/campaigns/{cid}/stats').json()
    print(f"Campaign {cid} ({lc['name']}): stats={stats}")
