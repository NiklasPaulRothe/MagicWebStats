import os
from urllib.parse import urlparse

from celery import Celery

app = Celery(
    'magicstats_celery',
    broker = urlparse(os.environ.get("REDIS_URL")),
    backend = urlparse(os.environ.get("REDIS_URL")),
)

@app.task
def testjob():
    print('testjob')