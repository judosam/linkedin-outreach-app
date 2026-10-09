import sqlite3
import requests

con = sqlite3.connect("app_data/app_data.db")
cur = con.cursor()

print("=== Comparing Highest ID Leads (Newest) ===")
local_desc = cur.execute("SELECT id, full_name, company FROM leads ORDER BY id DESC LIMIT 5").fetchall()
print("Local (DESC):", local_desc)

s = requests.Session()
s.post('https://outreach-app-7zc5l7znlq-uc.a.run.app/api/login', json={'username': 'admin', 'password': 'Admin@_2026!'})
r = s.get('https://outreach-app-7zc5l7znlq-uc.a.run.app/api/leads?limit=5')
live_items = [(i['id'], i['full_name'], i['company']) for i in r.json().get('items', [])]
print("Live (DESC): ", live_items)

print("\n=== Comparing Lowest ID Leads (Oldest) ===")
local_asc = cur.execute("SELECT id, full_name, company FROM leads ORDER BY id ASC LIMIT 5").fetchall()
print("Local (ASC): ", local_asc)

# Check if user filters by campaign or account in web UI
print("\n=== Campaign & Account Counts ===")
print("Local campaigns count:", cur.execute("SELECT count(*) FROM campaigns").fetchone()[0])
print("Local accounts count:", cur.execute("SELECT count(*) FROM accounts").fetchone()[0])

live_campaigns = s.get('https://outreach-app-7zc5l7znlq-uc.a.run.app/api/campaigns').json()
print("Live campaigns count:", len(live_campaigns))

live_accounts = s.get('https://outreach-app-7zc5l7znlq-uc.a.run.app/api/accounts').json()
print("Live accounts count:", len(live_accounts))
