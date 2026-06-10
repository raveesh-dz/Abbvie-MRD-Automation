Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$female = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Gender -eq 'Female' } | Select-Object -First 1
if ($female) { $s.SelectVoice($female.VoiceInfo.Name) }
$s.Speak('I need attention')
$s.Dispose()
