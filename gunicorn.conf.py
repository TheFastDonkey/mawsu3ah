"""Gunicorn production configuration."""

import multiprocessing

bind = "0.0.0.0:8000"
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 100
timeout = 30
keepalive = 5

errorlog = "-"
accesslog = "-"
loglevel = "info"

preload_app = True
