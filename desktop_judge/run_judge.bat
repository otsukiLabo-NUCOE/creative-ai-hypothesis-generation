@echo off
setlocal
cd /d "%~dp0"
REM ------------------------------------------------------------------
REM  Blinded LLM-as-judge evaluation. Double-click to start.
REM  Optional: set NGL=<number> below to force the number of GPU layers
REM  (leave empty = llama.cpp fits the model to GPU memory automatically).
REM ------------------------------------------------------------------
set NGL=
set PORT=8090

if not exist "llama\llama-server.exe" (
  echo llama\llama-server.exe not found. See the manual, STEP 3.
  pause
  exit /b 1
)
echo ============================================================
echo  Which model do you want to use?
echo   1 : Llama-3.3-70B-Instruct-Q3_K_M   [recommended: 16 GB dedicated GPU memory]
echo   2 : Qwen2.5-32B-Instruct-Q4_K_M
echo   3 : Qwen2.5-14B-Instruct-Q6_K
echo   4 : Llama-3.3-70B-Instruct-Q4_K_M   [24 GB or more]
echo ============================================================
set /p CHOICE=Number (1/2/3/4):
if "%CHOICE%"=="1" set MODEL=Llama-3.3-70B-Instruct-Q3_K_M
if "%CHOICE%"=="2" set MODEL=Qwen2.5-32B-Instruct-Q4_K_M
if "%CHOICE%"=="3" set MODEL=Qwen2.5-14B-Instruct-Q6_K
if "%CHOICE%"=="4" set MODEL=Llama-3.3-70B-Instruct-Q4_K_M
if "%MODEL%"=="" (
  echo Invalid number.
  pause
  exit /b 1
)
if not exist "models\%MODEL%.gguf" (
  echo models\%MODEL%.gguf not found. Run download_model.bat first.
  pause
  exit /b 1
)
if not exist "results\%MODEL%" mkdir "results\%MODEL%"

REM record the environment (for the paper's reproducibility statement)
(echo model=%MODEL% & echo date=%DATE% %TIME%) > "results\%MODEL%\environment.txt"
nvidia-smi >> "results\%MODEL%\environment.txt" 2>&1
"llama\llama-server.exe" --version >> "results\%MODEL%\environment.txt" 2>&1

set NGLARG=
if not "%NGL%"=="" set NGLARG=-ngl %NGL%
echo Starting the model server (loading can take several minutes)...
start "llama-server (do not close)" /min cmd /c ""llama\llama-server.exe" -m "models\%MODEL%.gguf" --host 127.0.0.1 --port %PORT% -c 10240 %NGLARG% > "results\%MODEL%\server.log" 2>&1"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; for($i=0;$i -lt 360;$i++){ try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 http://127.0.0.1:%PORT%/health; if($r.Content -match 'ok'){ $ok=$true; break } } catch {}; Start-Sleep 5 }; if(-not $ok){ Write-Host 'The server did not start. See results\%MODEL%\server.log'; exit 1 }"
if errorlevel 1 (
  taskkill /im llama-server.exe /f >nul 2>&1
  pause
  exit /b 1
)
echo Server ready. Judging starts now. Do not let the PC sleep.
REM hypothesis sets first (short; most important), then manuscripts (absolute scores, pairwise comparisons)
powershell -NoProfile -ExecutionPolicy Bypass -File "judge.ps1" -Endpoint "http://127.0.0.1:%PORT%/v1/chat/completions" -ModelLabel "%MODEL%" -Stage hypotheses
powershell -NoProfile -ExecutionPolicy Bypass -File "judge.ps1" -Endpoint "http://127.0.0.1:%PORT%/v1/chat/completions" -ModelLabel "%MODEL%" -Stage all
taskkill /im llama-server.exe /f >nul 2>&1
echo.
echo Finished. Copy the folder  results\%MODEL%  to the laptop (see the manual, STEP 6).
pause
