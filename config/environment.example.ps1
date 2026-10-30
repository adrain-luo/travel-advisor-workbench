# Optional local configuration. Keep actual account bindings outside Git.
$env:TRAVEL_DATA_DIR = Join-Path $env:LOCALAPPDATA 'TravelAdvisorWorkbench\data'
$env:TRAVEL_ENABLE_LIVE_COLLECTION = '0'
$env:TRAVEL_ENABLE_FOREGROUND_COLLECTION = '0'
# $env:TRAVEL_CJK_FONT = 'C:\Fonts\YourLicensedChineseFont.ttc'
