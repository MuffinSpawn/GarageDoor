from datetime import datetime
import pytz
from tinydb import TinyDB, Query

db = TinyDB('event_db.json')
local_tz = pytz.utc

records = db.all()
for entry in records:
    timestamp = int(pytz.utc.localize(datetime.strptime(entry['Timestamp'], '%Y-%m-%d %H:%M:%S')).timestamp())
    entry['timestamp'] = timestamp
db.write_back(records)
