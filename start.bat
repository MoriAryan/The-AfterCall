@echo off
echo Starting The AfterCall...

REM Load .env if it exists
if exist .env (
    for /f "tokens=1,* delims==" %%a in (.env) do (
        if not "%%a"=="" if not "%%a:~0,1%"=="#" set "%%a=%%b"
    )
)

REM Start backend
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
