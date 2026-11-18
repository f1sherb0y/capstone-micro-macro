@echo off
setlocal
wsl.exe -e bash -lc "cd /mnt/d/hkura/codedemo_v2 && .venv/bin/python validation/full_352_cases/run_validation.py %*"
exit /b %ERRORLEVEL%
