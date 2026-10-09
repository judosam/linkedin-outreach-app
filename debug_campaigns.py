from app.database import SessionLocal
from app.models import Campaign

db = SessionLocal()
campaigns = db.query(Campaign).all()
print(f"Campaigns: {len(campaigns)}")
for c in campaigns:
    print(f" - {c.campaign_key}: links = {len(c.account_links)}")
