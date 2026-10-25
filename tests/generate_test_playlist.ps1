Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$playlistDir = Join-Path $PSScriptRoot "test_playlist"
New-Item -ItemType Directory -Force -Path $playlistDir | Out-Null

# Track 1: Clean track
$track1 = Join-Path $playlistDir "track1_clean.wav"
$synth.SetOutputToWaveFile($track1)
$synth.Speak("This is a clean track. Welcome to the show. We hope you enjoy the music.")

# Track 2: Explicit track
$track2 = Join-Path $playlistDir "track2_explicit.wav"
$synth.SetOutputToWaveFile($track2)
$synth.Speak("Yo check this out. Stop being a bitch and listen. Damn right.")

$synth.Dispose()
Write-Host "Generated test playlist files successfully in $playlistDir"
