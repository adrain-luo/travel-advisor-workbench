param(
    [string]$ImagePath,
    [string]$Language = "zh-Hans-CN",
    [switch]$ListLanguages
)

# Windows PowerShell 5 projects these stock WinRT APIs; PowerShell 7 does not.
# This helper reads one supplied local image and never captures or controls UI.
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]

if ($ListLanguages) {
    [ordered]@{
        languages = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag })
        max_image_dimension = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension
    } | ConvertTo-Json -Compress
    exit 0
}

$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$ocrAsTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq "AsTask" -and $_.IsGenericMethod -and
    $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1

function Wait-OcrResult($Operation, $ResultType) {
    $task = $ocrAsTask.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}

$ocrBitmap = $null
$ocrStream = $null
try {
    $ocrLanguage = New-Object Windows.Globalization.Language($Language)
    $ocrEngine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($ocrLanguage)
    if ($null -eq $ocrEngine) { throw "Requested OCR language is unavailable" }
    $ocrFile = Wait-OcrResult ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
    $ocrStream = Wait-OcrResult ($ocrFile.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $ocrDecoder = Wait-OcrResult ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($ocrStream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $ocrBitmap = Wait-OcrResult ($ocrDecoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    if ($ocrBitmap.PixelWidth -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension -or
        $ocrBitmap.PixelHeight -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension) {
        throw "Image exceeds the local OCR dimension limit"
    }
    $ocrResult = Wait-OcrResult ($ocrEngine.RecognizeAsync($ocrBitmap)) ([Windows.Media.Ocr.OcrResult])
    [ordered]@{
        language = $ocrEngine.RecognizerLanguage.LanguageTag
        width = $ocrBitmap.PixelWidth
        height = $ocrBitmap.PixelHeight
        text_angle = $ocrResult.TextAngle
        lines = @($ocrResult.Lines | ForEach-Object {
            [ordered]@{
                text = $_.Text
                words = @($_.Words | ForEach-Object {
                    [ordered]@{text = $_.Text; bounds = [ordered]@{
                        x = $_.BoundingRect.X; y = $_.BoundingRect.Y
                        width = $_.BoundingRect.Width; height = $_.BoundingRect.Height
                    }}
                })
            }
        })
    } | ConvertTo-Json -Depth 7 -Compress
} finally {
    if ($null -ne $ocrBitmap) { $ocrBitmap.Dispose() }
    if ($null -ne $ocrStream) { $ocrStream.Dispose() }
}
