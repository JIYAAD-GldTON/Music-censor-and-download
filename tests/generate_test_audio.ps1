Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$target = Join-Path $PSScriptRoot "test_sample.wav"
$synth.SetOutputToWaveFile($target)
$synth.Speak("Hello everyone. What the fuck is going on here? This is total bullshit. Have a great day.")
$synth.Dispose()
Write-Host "Generated test_sample.wav successfully at $target"
