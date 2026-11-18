"""Stand-alone job worker:  python -m app.worker [--once]

Use this in production (one worker process) and set CAREFLOW_SCHEDULER=off on every API instance.
"""
import logging
import sys
import time

from app.core.config import get_settings
from app.jobs import run_all


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    if '--once' in sys.argv:
        print(run_all('worker --once'))
        return 0
    every = get_settings().scheduler_interval_seconds
    logging.info('CareFlow worker running jobs every %ss (Ctrl+C to stop)', every)
    while True:
        logging.info('Run: %s', run_all('worker'))
        time.sleep(every)


if __name__ == '__main__':
    sys.exit(main())
