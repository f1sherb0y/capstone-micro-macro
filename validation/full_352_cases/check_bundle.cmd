@echo off
setlocal
wsl.exe -e bash -lc "cd /mnt/d/hkura/codedemo_v2 && CODEDEMO_PROGRESS=0 .venv/bin/python validation/full_352_cases/run_validation.py --profile smoke --max-cases 2 --local-test-client --output-dir validation/full_352_cases/mock_results"
exit /b %ERRORLEVEL%
