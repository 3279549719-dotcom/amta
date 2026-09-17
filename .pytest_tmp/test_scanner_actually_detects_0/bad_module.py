import subprocess
def f():
    return subprocess.run(['git', 'log'], capture_output=True, text=True)
