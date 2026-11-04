"""Compile the small Windows-only IME shim with Visual Studio C++ tools."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    where = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    install = subprocess.check_output([str(where), '-latest', '-products', '*', '-requires',
                                      'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
                                      '-property', 'installationPath'], text=True).strip()
    if not install:
        raise SystemExit('Visual Studio C++ Build Tools (x64) are required to build the IME preview.')
    build = ROOT / 'build' / 'ime'
    build.mkdir(parents=True, exist_ok=True)
    environment = Path(install) / 'VC/Auxiliary/Build/vcvars64.bat'
    source = ROOT / 'native/ime_preview.c'
    output = ROOT / 'native/ime_preview.dll'
    args = ['cl', '/nologo', '/LD', '/O2', '/W4', '/MT', '/DUNICODE', '/D_UNICODE', str(source),
            '/link', '/OUT:' + str(output), 'user32.lib', 'imm32.lib', 'comctl32.lib']
    script = build / 'compile.cmd'
    script.write_text('@echo off\nchcp 65001 >nul\ncall ' + subprocess.list2cmdline([str(environment)])
                      + ' >nul\nif errorlevel 1 exit /b 1\n' + subprocess.list2cmdline(args)
                      + '\n', encoding='utf-8')
    subprocess.run([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', str(script)], cwd=build, check=True)


if __name__ == '__main__':
    main()
