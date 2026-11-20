# k5 loudspeaker isolation

The desktop PulseAudio server has only `desktop_silent`, a muted null sink.
GENIAC uses a separate server and session bus, holding ALSA `hw:PCH,0` open
without idle suspension. `geniac-sensor` explicitly selects that server for
ffplay and the recording monitor. A missing private server causes startup /
playback failure, not fallback to desktop audio. This configuration is for k5;
do not install the desktop configuration on the mother PC.

Install `desktop.pa` as `~/.config/pulse/default.pa`, backing up any existing
file first. Install `scripts/deploy/geniac-audio.service` and the updated
`geniac-sensor.service` in `~/.config/systemd/user/`. Stop geniac-sensor before
switching, restart pulseaudio.service, reload user units, enable/start
geniac-audio.service, then start geniac-sensor.service. Disable GNOME
`org.gnome.desktop.sound` event-sounds and input-feedback-sounds as well.

This intentionally removes desktop hardware audio devices, including microphone
inputs. The GENIAC camera video and output-monitor audio recording are unaffected.
Applications explicitly accessing ALSA or the private socket are outside normal
desktop routing; this is audio isolation, not a security boundary.

Rollback: stop geniac-sensor and disable/stop geniac-audio; restore the saved
PulseAudio default.pa (or remove it if none previously existed), restart desktop
pulseaudio, and remove the private PULSE_SERVER/PULSE_SINK/SDL_AUDIODRIVER setup
from geniac-sensor before using the desktop output again.

Validated on k5 using a finite silent WAV: default ffplay reaches only the muted
null sink; scenario ffplay reaches only the private ALSA sink; its monitor can be
recorded by FFmpeg. No audible loudspeaker test was performed.
