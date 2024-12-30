web: gunicorn webstats:app
worker: rq worker -u $REDIS_URL?ssl_cert_reqs=none magicstats-tasks