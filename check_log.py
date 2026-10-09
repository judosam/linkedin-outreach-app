import sqlite3
db = sqlite3.connect('app_data/app_data.db')
rows = db.execute("SELECT log_text FROM run_logs WHERE job_type='check_replies' ORDER BY id DESC LIMIT 1").fetchall()
if rows and rows[0]:
    print(rows[0][0].encode('utf-8', 'ignore').decode('utf-8'))
else:
    print("No logs")
