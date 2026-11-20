# Reference implementations

- Workspace manifest: air-water2026/armadillo_ros2_ws, add_deer_detector, commit 3266a78e4ea9a0ef5c766a54842bff4ffef5f82e.
- Detector source/model/fixture: air-water2026/livox_deer_detector, add_deer_detector, commit bb483c7d20708fa03458467ae7975be835e2a103. Original package license: Proprietary; attribution: SpesTech. Core detector, classifier, model, cloud decoding and transport safeguards are adapted here. ICP is removed; outputs and downstream integration are changed for stationary use. Original model provenance is retained next to the model.
- Scenario design reference: air-water2026/scenario-sound, commit 19679fc14c6ee5153d0c91c92597ddf47a1c886c. The concept/timeline/asset separation, recorded-sound editing, reaction labels and offline rendering inform an independently implemented tree engine. No runtime dependency on that checkout.

The reference model is experimental and not a validated deer-versus-other-animal guarantee. The inherited proprietary material is not relicensed by this repository.

## Weather and hunting-story adaptation

- Reference story workflow: `/tmp/geniac-sound-reference/scenario_app/designer.py`, concept → sound needs → recordings → timeline. GENIAC constructs the whole branching story offline and follows sensor responses during playback.
- Sakimui location reference: https://geoshape.ex.nii.ac.jp/nrct/resource/01/010000529000.html (43.828328, 145.090059). User spelling 崎無為 is interpreted as 標津町崎無異.
- Online weather: https://open-meteo.com/en/docs ; current `weather_code,rain,snowfall`, Asia/Tokyo. Weather attribution and timestamps are stored in each story. Snow/rain/clear selects snow/puddles/grass footsteps; dry cloudy/fog defaults to grass. Ground cover is not observed directly.
- Each downloaded Freesound asset retains its individual source URL, author and license in the local stock provenance. No recording is described as auditioned.
