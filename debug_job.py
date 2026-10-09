from app.database import SessionLocal
from app.jobs import job_check_replies

print("Running check replies manually...")
job_check_replies()
print("Done")
