"""開発サーバー起動スクリプト

uvicornのreload=Trueは子プロセスを生成する。
親を強制終了すると子が孤児になりポートを占有し続ける問題がある。
Windows Job Objectを使い、親が死んだら子も自動終了するようにする。
"""

import os
import sys
from pathlib import Path

# server モジュールが project/agent_manager/ 配下にあるためパスを追加
# uvicornのreload子プロセスでも有効にするため、__main__ブロックの外で設定する
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn

DEFAULT_PORT = 8300


def _setup_job_object():
    """Windows Job Objectを作成し、現プロセスに紐づける。
    親プロセスが終了すると、子プロセスも自動的にOSに終了させる。
    """
    if sys.platform != "win32":
        return

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32

    # Job Object作成
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return

    # JOBOBJECT_EXTENDED_LIMIT_INFORMATION 構造体
    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = 0x2000

    # JobObjectExtendedLimitInformation = 9
    kernel32.SetInformationJobObject(
        job, 9, ctypes.byref(info), ctypes.sizeof(info)
    )

    # 現プロセスをJobに登録
    handle = kernel32.OpenProcess(0x1F0FFF, False, ctypes.windll.kernel32.GetCurrentProcessId())
    kernel32.AssignProcessToJobObject(job, handle)
    kernel32.CloseHandle(handle)

    # jobハンドルはプロセス終了まで保持（GCで閉じられないようグローバルに保存）
    return job


if __name__ == "__main__":
    # cwdをリポジトリルートに固定（agent/ ディレクトリが相対パスで見えるように）
    project_root = Path(__file__).resolve().parent.parent.parent
    os.chdir(project_root)

    _job = _setup_job_object()
    port = int(os.environ.get("KOBITO_PORT", DEFAULT_PORT))
    uvicorn.run("server.app:create_app", host="0.0.0.0", port=port, reload=True, factory=True)
