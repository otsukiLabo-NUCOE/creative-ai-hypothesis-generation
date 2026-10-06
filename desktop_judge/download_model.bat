@echo off
setlocal
cd /d "%~dp0"
if not exist models mkdir models
echo ============================================================
echo  Download the judge model (choose by DEDICATED GPU memory)
echo ------------------------------------------------------------
echo  1 : Llama-3.3-70B-Instruct  Q3_K_M  (34.3 GB)  dedicated GPU memory 16 GB  [recommended for this PC]
echo  2 : Qwen2.5-32B-Instruct    Q4_K_M  (19.9 GB)  dedicated GPU memory 12-24 GB (faster)
echo  3 : Qwen2.5-14B-Instruct    Q6_K    (12.1 GB)  dedicated GPU memory 8-12 GB
echo  4 : Llama-3.3-70B-Instruct  Q4_K_M  (42.5 GB)  dedicated GPU memory 24 GB or more
echo ============================================================
set /p CHOICE=Number (1/2/3/4):
if "%CHOICE%"=="1" (
  set FILE=Llama-3.3-70B-Instruct-Q3_K_M.gguf
  set URL=https://huggingface.co/bartowski/Llama-3.3-70B-Instruct-GGUF/resolve/main/Llama-3.3-70B-Instruct-Q3_K_M.gguf
) else if "%CHOICE%"=="2" (
  set FILE=Qwen2.5-32B-Instruct-Q4_K_M.gguf
  set URL=https://huggingface.co/bartowski/Qwen2.5-32B-Instruct-GGUF/resolve/main/Qwen2.5-32B-Instruct-Q4_K_M.gguf
) else if "%CHOICE%"=="3" (
  set FILE=Qwen2.5-14B-Instruct-Q6_K.gguf
  set URL=https://huggingface.co/bartowski/Qwen2.5-14B-Instruct-GGUF/resolve/main/Qwen2.5-14B-Instruct-Q6_K.gguf
) else if "%CHOICE%"=="4" (
  set FILE=Llama-3.3-70B-Instruct-Q4_K_M.gguf
  set URL=https://huggingface.co/bartowski/Llama-3.3-70B-Instruct-GGUF/resolve/main/Llama-3.3-70B-Instruct-Q4_K_M.gguf
) else (
  echo Invalid number.
  pause
  exit /b 1
)
echo Downloading %FILE% ... (this can take 30-90 minutes; it resumes if interrupted - just run this file again)
curl.exe -L --retry 10 --retry-delay 10 -C - -o "models\%FILE%" "%URL%"
if errorlevel 1 (
  echo Download failed or interrupted. Run download_model.bat again to resume.
) else (
  echo Finished: models\%FILE%
)
pause
