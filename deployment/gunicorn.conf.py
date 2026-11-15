# Gunicorn Configuration for DigiBook Web Application
# Optimized for Raspberry Pi 3B+ (4 Cores @ 1.4GHz, 1GB RAM)

import multiprocessing

bind = "127.0.0.1:5000"

# Keep worker count conservative so CPU and RAM remain available for the local OpenCV tracking app
workers = 2
threads = 2
worker_class = "gthread"

# Request timeouts
timeout = 30
keepalive = 5

# Memory leak prevention: restart worker after 1000 requests with jitter
max_requests = 1000
max_requests_jitter = 50

# Logging
accesslog = "/home/pi/DigiBook/logs/access.log"
errorlog = "/home/pi/DigiBook/logs/error.log"
loglevel = "warning"

# Process naming
proc_name = "digibook_web"
