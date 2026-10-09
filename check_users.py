import sqlite3, json

con = sqlite3.connect("app_data/app_data.db")
cur = con.cursor()

print("=== Users Table ===")
for r in cur.execute("SELECT id, username, role, active, allowed_campaign_ids, allowed_account_ids FROM users").fetchall():
    print(r)

print("\n=== Campaigns Table ===")
for r in cur.execute("SELECT id, name, status FROM campaigns").fetchall():
    print(r)

print("\n=== Accounts Table ===")
for r in cur.execute("SELECT id, name, status FROM accounts").fetchall():
    print(r)
