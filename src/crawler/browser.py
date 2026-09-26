"""用本機 Chrome 無頭模式取得 JS 渲染後的 DOM。

Chrome 在 macOS 上輸出 DOM 後程序不一定會結束，所以用 timeout 收尾，並保留已輸出的內容。
"""
import subprocess
import tempfile

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def render_dom(url: str, budget_ms: int = 15000, timeout: int = 25) -> str:
    with tempfile.TemporaryDirectory() as profile:
        cmd = [CHROME, "--headless=new", "--disable-gpu", f"--user-data-dir={profile}",
               f"--virtual-time-budget={budget_ms}", "--dump-dom", url]
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=timeout).stdout
        except subprocess.TimeoutExpired as e:
            out = e.stdout or b""
    return out.decode("utf-8", errors="replace")
