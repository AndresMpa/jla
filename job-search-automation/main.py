"""Entrypoint: python main.py [-c config.yaml] [-p profile_name ...]

Runs every profile in profiles/ by default (or just the ones passed with
-p/--profile), against the same fetched listings, writing each profile's
own report to profiles/output/<name>/.
"""

from src.job_search.cli import main

if __name__ == "__main__":
    main()
