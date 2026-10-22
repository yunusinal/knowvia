# GPU ile yeniden sıralama için ayrı bir sanal ortam kurar (ADR-11).
#
# Neden ayrı ortam: fastembed CPU paketi `onnxruntime`'a bağlıdır; `onnxruntime-gpu` aynı Python
# modülünü (onnxruntime) kurduğu için ikisi aynı ortamda bulunamaz. Paket sürümleri uv.lock ile aynıdır.
# Gerekenler: NVIDIA sürücüsü ve `nvidia-smi` çıktısında CUDA 13+. CUDA Toolkit/cuDNN kurmak GEREKMEZ;
# bu kütüphaneler pip paketleri olarak gelir ve onnxruntime.preload_dlls() ile yüklenir.
#
# Kullanım (repo kökünden):  powershell -ExecutionPolicy Bypass -File scripts\setup_gpu_env.ps1
param([string]$VenvPath = ".venv-gpu")
$ErrorActionPreference = "Stop"

$requirements = Join-Path $env:TEMP "knowvia-gpu-requirements.txt"
$exported = uv export --frozen --no-hashes --no-emit-project --all-groups
$ortLine = $exported | Where-Object { $_ -match '^onnxruntime==' } | Select-Object -First 1
if (-not $ortLine) { throw "uv.lock içinde onnxruntime bulunamadı." }
$ortVersion = ($ortLine -split '==')[1].Split(';')[0].Trim()
$exported | Where-Object { $_ -notmatch '^onnxruntime==' -and $_ -notmatch '^\s*#' } | Set-Content -Encoding utf8 $requirements

uv venv $VenvPath --python 3.12
$python = Join-Path $VenvPath "Scripts\python.exe"
# 1) Kilitli bağımlılıklar + GPU paketi ve CUDA/cuDNN pip paketleri.
uv pip install --python $python -r $requirements "onnxruntime-gpu[cuda,cudnn]==$ortVersion"
# 2) fastembed bağımlılık olarak CPU paketini de kurar ve onnxruntime klasörünü ezer; ikisini de kaldır,
#    GPU paketini bağımlılıksız yeniden kur (CUDA/cuDNN paketleri 1. adımdan yerinde kalır).
uv pip uninstall --python $python onnxruntime onnxruntime-gpu
uv pip install --python $python --no-deps "onnxruntime-gpu==$ortVersion"

& $python -c "import onnxruntime as o; o.preload_dlls(directory=''); p = o.get_available_providers(); print(p); assert 'CUDAExecutionProvider' in p, 'CUDA sağlayıcısı yok: sürücüyü ve nvidia-smi CUDA sürümünü kontrol edin'"
Write-Host "Hazır. .env içinde GPU_ENABLED=true yapın ve API'yi şu komutla başlatın:"
Write-Host "  $python -m uvicorn app.main:app"
