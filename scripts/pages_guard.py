import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.pages import guard

if __name__ == '__main__':
    allowed, reason = guard()
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write(f'deploy={str(allowed).lower()}\nreason={reason}\n')
    print(reason)
