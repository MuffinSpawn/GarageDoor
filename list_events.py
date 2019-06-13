from datetime import datetime
import pytz
from tinydb import TinyDB
from pprint import pprint, pformat

db = TinyDB('event_db.json')

local_tz = pytz.timezone('America/Chicago')
for record in db.all():
    timestamp = datetime.fromtimestamp(record['timestamp'], local_tz)
    date_and_time = timestamp.strftime('%Y-%m-%d %H:%M:%S %z')
    print('{} {} {} {}'.format(date_and_time, record['State'], record['SideDoorState'], record['StateUpdate']))
# print(pformat(str(db.all())))
