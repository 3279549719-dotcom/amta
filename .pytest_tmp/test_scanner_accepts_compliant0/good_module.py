import subprocess
def f():
    return subprocess.run(['git', 'log'], capture_output=True,
                          text=True, encoding='utf-8', errors='replace')
