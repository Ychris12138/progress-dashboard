from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.pages import assert_empty

if __name__ == '__main__':
    assert_empty(Path(__file__).resolve().parents[1])
    print('Empty public dataset verified')
