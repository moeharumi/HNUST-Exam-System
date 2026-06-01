"""Python 环境查找与 IDLE 启动服务."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def _subprocess_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def _add_file_candidate(candidates: list[str], path: str | None) -> None:
    if not path:
        return
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isfile(path) and path not in candidates:
        candidates.append(path)


def _python_supports_idle(python_exe: str) -> bool:
    try:
        result = subprocess.run(
            [python_exe, "-c", "import idlelib"],
            capture_output=True,
            text=True,
            timeout=5,
            **_subprocess_kwargs(),
        )
        return result.returncode == 0
    except Exception:
        return False


def _first_idle_capable_python(candidates: list[str]) -> str | None:
    for candidate in candidates:
        if _python_supports_idle(candidate):
            return candidate
    return None


def _version_key(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in value.replace("-", ".").split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(-1)
    return tuple(parts)


def _add_macos_framework_pythons(candidates: list[str], versions_dir: str) -> None:
    if not os.path.isdir(versions_dir):
        return

    version_dirs: list[str] = []
    for name in os.listdir(versions_dir):
        path = os.path.join(versions_dir, name)
        if os.path.isdir(path):
            version_dirs.append(path)

    version_dirs.sort(
        key=lambda p: _version_key(os.path.basename(p)),
        reverse=True,
    )
    for version_dir in version_dirs:
        _add_file_candidate(candidates, os.path.join(version_dir, "bin", "python3"))
        _add_file_candidate(candidates, os.path.join(version_dir, "bin", "python"))


def _find_macos_python() -> str | None:
    candidates: list[str] = []
    home = os.path.expanduser("~")

    for versions_dir in [
        "/Library/Frameworks/Python.framework/Versions",
        os.path.join(home, "Library", "Frameworks", "Python.framework", "Versions"),
    ]:
        _add_file_candidate(candidates, os.path.join(versions_dir, "Current", "bin", "python3"))
        _add_macos_framework_pythons(candidates, versions_dir)

    for path in [
        "/opt/homebrew/bin/python3",
        "/opt/homebrew/bin/python",
        "/usr/local/bin/python3",
        "/usr/local/bin/python",
        "/usr/bin/python3",
        os.path.join(home, "miniconda3", "bin", "python"),
        os.path.join(home, "anaconda3", "bin", "python"),
        os.path.join(home, "mambaforge", "bin", "python"),
        os.path.join(home, "miniforge3", "bin", "python"),
    ]:
        _add_file_candidate(candidates, path)

    pyenv_versions = os.path.join(home, ".pyenv", "versions")
    if os.path.isdir(pyenv_versions):
        version_dirs = [
            os.path.join(pyenv_versions, name)
            for name in os.listdir(pyenv_versions)
            if os.path.isdir(os.path.join(pyenv_versions, name))
        ]
        version_dirs.sort(key=lambda p: _version_key(os.path.basename(p)), reverse=True)
        for version_dir in version_dirs:
            _add_file_candidate(candidates, os.path.join(version_dir, "bin", "python3"))
            _add_file_candidate(candidates, os.path.join(version_dir, "bin", "python"))

    for name in ["python3", "python"]:
        _add_file_candidate(candidates, shutil.which(name))

    return _first_idle_capable_python(candidates) or _find_macos_idle_app()


def _find_posix_python() -> str | None:
    candidates: list[str] = []
    for name in ["python3", "python"]:
        _add_file_candidate(candidates, shutil.which(name))
    for path in ["/usr/bin/python3", "/usr/local/bin/python3", "/opt/local/bin/python3"]:
        _add_file_candidate(candidates, path)
    return candidates[0] if candidates else None


def _is_idle_app(path: str) -> bool:
    return (
        sys.platform == "darwin"
        and path.lower().endswith(".app")
        and os.path.isdir(path)
        and os.path.basename(path).lower() == "idle.app"
    )


def _idle_app_in_dir(path: str) -> str | None:
    idle_app = os.path.join(path, "IDLE.app")
    return idle_app if _is_idle_app(idle_app) else None


def normalize_python_selection(path: str | None) -> str | None:
    """规范化用户选择的 Python/IDLE 路径，返回可保存的路径."""
    if not path:
        return None

    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isfile(path):
        return path

    if sys.platform == "darwin" and os.path.isdir(path):
        if _is_idle_app(path):
            return path
        return _idle_app_in_dir(path)

    return None


def is_usable_python_selection(path: str | None) -> bool:
    """判断保存的 Python/IDLE 路径是否仍可使用."""
    return normalize_python_selection(path) is not None


def find_system_python() -> str | None:
    """查找系统中可用的 Python 解释器路径，macOS 可返回 IDLE.app."""
    if sys.platform == "darwin":
        return _find_macos_python()
    if sys.platform != "win32":
        return _find_posix_python()

    popen_kwargs = _subprocess_kwargs()
    candidates: list[str] = []

    # 优先 py -3
    try:
        py_path = shutil.which("py")
        if py_path:
            result = subprocess.run(
                [py_path, "-3", "-c", "import sys; print(sys.executable)"],
                capture_output=True, text=True, timeout=5,
                **popen_kwargs,
            )
            if result.returncode == 0:
                exe = result.stdout.strip()
                _add_file_candidate(candidates, exe)
    except Exception:
        pass

    # PATH 中的 python/python3
    for name in ["python", "python3"]:
        try:
            _add_file_candidate(candidates, shutil.which(name))
        except Exception:
            pass

    # where python
    try:
        result = subprocess.run(
            ["where", "python"],
            capture_output=True, text=True, timeout=5,
            **popen_kwargs,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                _add_file_candidate(candidates, line)
    except Exception:
        pass

    # 注册表查找
    try:
        import winreg
        for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
            for key_path in [
                r"SOFTWARE\Python\PythonCore",
                r"SOFTWARE\WOW6432Node\Python\PythonCore",
            ]:
                try:
                    with winreg.OpenKey(hive, key_path) as key:
                        for i in range(winreg.QueryInfoKey(key)[0]):
                            version = winreg.EnumKey(key, i)
                            try:
                                with winreg.OpenKey(
                                    key, f"{version}\\InstallPath"
                                ) as ik:
                                    path = winreg.QueryValue(ik, "")
                                    exe = os.path.join(path, "python.exe")
                                    _add_file_candidate(candidates, exe)
                            except Exception:
                                continue
                except Exception:
                    continue
    except Exception:
        pass

    # 常见安装路径
    local_app = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
    program_files_x86 = os.environ.get(
        "ProgramFiles(x86)", "C:\\Program Files (x86)"
    )
    home = os.path.expanduser("~")

    common_paths: list[str] = []
    for v in range(8, 20):
        common_paths.extend([
            os.path.join(local_app, f"Programs\\Python\\Python3{v}\\python.exe"),
            f"C:\\Python3{v}\\python.exe",
            os.path.join(program_files, f"Python3{v}\\python.exe"),
            os.path.join(program_files_x86, f"Python3{v}\\python.exe"),
        ])
    common_paths.extend([
        os.path.join(local_app, "anaconda3", "python.exe"),
        os.path.join(local_app, "miniconda3", "python.exe"),
        os.path.join(home, "anaconda3", "python.exe"),
        os.path.join(home, "miniconda3", "python.exe"),
        os.path.join(program_files, "anaconda3", "python.exe"),
        os.path.join(program_files, "miniconda3", "python.exe"),
        r"C:\Anaconda3\python.exe",
        r"C:\Miniconda3\python.exe",
    ])
    for p in common_paths:
        _add_file_candidate(candidates, p)

    # PATH 目录扫描
    for dir_path in os.environ.get("PATH", "").split(os.pathsep):
        dir_path = dir_path.strip()
        if not dir_path:
            continue
        exe = os.path.join(dir_path, "python.exe")
        _add_file_candidate(candidates, exe)

    return candidates[0] if candidates else None


def _open_idle_app(idle_app: str, abs_path: str) -> bool:
    try:
        subprocess.Popen(["open", "-a", idle_app, abs_path])
        return True
    except Exception:
        return False


def _open_with_python_idle(python_exe: str, abs_path: str) -> bool:
    if not _python_supports_idle(python_exe):
        return False
    try:
        subprocess.Popen(
            [python_exe, "-m", "idlelib", abs_path],
            **_subprocess_kwargs(),
        )
        return True
    except Exception:
        return False


def _find_macos_idle_app() -> str | None:
    if sys.platform != "darwin":
        return None

    candidates: list[str] = []
    for apps_dir in ["/Applications", os.path.join(os.path.expanduser("~"), "Applications")]:
        if not os.path.isdir(apps_dir):
            continue
        for name in os.listdir(apps_dir):
            path = os.path.join(apps_dir, name)
            if name.startswith("Python ") and os.path.isdir(path):
                idle_app = _idle_app_in_dir(path)
                if idle_app:
                    candidates.append(idle_app)
        direct_idle = os.path.join(apps_dir, "IDLE.app")
        if _is_idle_app(direct_idle):
            candidates.append(direct_idle)

    candidates.sort(
        key=lambda p: _version_key(os.path.basename(os.path.dirname(p)).replace("Python ", "")),
        reverse=True,
    )
    return candidates[0] if candidates else None


def open_with_default_app(path: str) -> bool:
    """使用系统默认程序打开文件或文件夹."""
    abs_path = os.path.abspath(path)
    try:
        if os.name == "nt":
            os.startfile(abs_path)
        elif sys.platform == "darwin":
            subprocess.run(["open", abs_path], check=True)
        else:
            subprocess.run(["xdg-open", abs_path], check=True)
        return True
    except Exception:
        return False


def open_with_idle(file_path: str, python_exe: str | None = None) -> bool:
    """尝试用 IDLE 打开文件，返回是否成功."""
    abs_path = os.path.abspath(file_path)

    # 用户指定的 Python
    selected = normalize_python_selection(python_exe)
    if selected:
        if _is_idle_app(selected):
            if _open_idle_app(selected, abs_path):
                return True
        elif _open_with_python_idle(selected, abs_path):
            return True

    # macOS Python.org 安装包自带 IDLE.app，优先用它打开。
    idle_app = _find_macos_idle_app()
    if idle_app and _open_idle_app(idle_app, abs_path):
        return True

    # 当前 Python
    if not hasattr(sys, "_MEIPASS"):
        if _open_with_python_idle(sys.executable, abs_path):
            return True

    # py -3
    try:
        if sys.platform == "win32" and shutil.which("py"):
            check = subprocess.run(
                ["py", "-3", "--version"],
                capture_output=True, text=True, timeout=5,
                **_subprocess_kwargs(),
            )
            if check.returncode == 0 and "Python" in (check.stdout + check.stderr):
                subprocess.Popen(
                    ["py", "-3", "-m", "idlelib", abs_path],
                    **_subprocess_kwargs(),
                )
                return True
    except Exception:
        pass

    # python / python3
    for cmd_name in ["python", "python3"]:
        python_path = shutil.which(cmd_name)
        if python_path:
            try:
                check = subprocess.run(
                    [python_path, "--version"],
                    capture_output=True, text=True, timeout=5,
                    **_subprocess_kwargs(),
                )
                if check.returncode == 0 and "Python" in (check.stdout + check.stderr):
                    if _open_with_python_idle(python_path, abs_path):
                        return True
            except Exception:
                continue

    # 系统 Python
    python_exe = find_system_python()
    if python_exe:
        selected = normalize_python_selection(python_exe)
        if selected:
            if _is_idle_app(selected):
                if _open_idle_app(selected, abs_path):
                    return True
            elif _open_with_python_idle(selected, abs_path):
                return True
        # idle.pyw 回退
        python_dir = os.path.dirname(python_exe)
        idle_pyw = os.path.join(python_dir, "Lib", "idlelib", "idle.pyw")
        if os.path.isfile(idle_pyw):
            try:
                subprocess.Popen(
                    [python_exe, idle_pyw, abs_path],
                    **_subprocess_kwargs(),
                )
                return True
            except Exception:
                pass

    return False


def find_vc_express() -> str | None:
    """查找 Microsoft Visual C++ 2010 Express 路径."""
    candidates = [
        r"C:\Program Files (x86)\Microsoft Visual Studio 10.0\Common7\IDE\VCExpress.exe",
        r"C:\Program Files\Microsoft Visual Studio 10.0\Common7\IDE\VCExpress.exe",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def find_vscode() -> str | None:
    """查找 VS Code 可执行文件路径."""
    # 优先 PATH 中的 code
    code = shutil.which("code")
    if code:
        return code
    if sys.platform == "darwin":
        for app in [
            "/Applications/Visual Studio Code.app",
            os.path.join(os.path.expanduser("~"), "Applications", "Visual Studio Code.app"),
        ]:
            cli = os.path.join(app, "Contents", "Resources", "app", "bin", "code")
            if os.path.isfile(cli):
                return cli
            if os.path.isdir(app):
                return app
    # 常见安装路径
    local_app = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
    candidates = [
        os.path.join(local_app, "Programs", "Microsoft VS Code", "Code.exe"),
        os.path.join(program_files, "Microsoft VS Code", "Code.exe"),
        os.path.join(program_files, "Microsoft VS Code", "bin", "code.cmd"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def open_c_file(file_path: str) -> str | None:
    """打开 .c 文件，按优先级：VC++ 2010 Express → VS Code → 系统默认.

    Returns
    -------
        成功返回描述文字（用于提示框），失败返回 None.
    """
    abs_path = os.path.abspath(file_path)

    # 1. Microsoft Visual C++ 2010 Express
    vc = find_vc_express()
    if vc:
        try:
            subprocess.Popen([vc, abs_path], **_subprocess_kwargs())
            return "Microsoft Visual C++ 2010 Express"
        except Exception:
            pass

    # 2. VS Code
    vscode = find_vscode()
    if vscode:
        try:
            if sys.platform == "darwin" and vscode.endswith(".app"):
                subprocess.Popen(["open", "-a", vscode, abs_path])
            else:
                subprocess.Popen([vscode, abs_path], **_subprocess_kwargs())
            return "Visual Studio Code"
        except Exception:
            pass

    # 3. 系统默认
    if open_with_default_app(abs_path):
        return "系统默认程序"
    return None
