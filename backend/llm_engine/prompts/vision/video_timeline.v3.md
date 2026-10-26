You watch one video recording from the drive of a rocket propulsion team, given as frames taken from the clip. Each frame is preceded by its time in seconds from the start of the clip. The team films many things: hot firings in a test cell, cold-flow and leak tests, inspections and de-integration of hardware after a test, assembly and integration steps, walkthroughs of a test setup, screen recordings, and more.

First decide what this recording shows, from the frames and from the file's metadata (its name, folder, labels and the files next to it). Trust the frames over the folder: a clip kept in a firing campaign's folder can still show an inspection.

Return:
- recording_kind, exactly one of: firing (a thruster or engine is fired), cold_flow (a fluid flows through the hardware without firing), leak_check, inspection (hardware is looked at, probed or taken apart, including de-integration after a test), assembly (hardware is put together or installed), setup (a walk around or along a test setup), screen (a recording of a screen or a program), other.
- summary: two or three sentences in English on what the recording shows and what happens in it.
- events: each observable event with t_s (seconds from the clip start, taken from the frame timestamps), a short type in snake_case that names what happens, and a short English description of what is visible. For a firing use ignition, steady_plume, shutdown, spark_shower, flash, smoke or debris where they fit; for other recordings name the action, for example tool_contact, part_removed, part_installed, valve_action, leak_bubbles, camera_moves.
- anomalies: anything unusual for this kind of recording, such as an asymmetric plume, burning hardware, ejected parts, visible damage, a leak, or a broken or missing part, each with its timestamp in the text. Leave it empty when nothing is unusual.

Only for a firing: ignition is the first frame in which the thruster is firing (a plume or jet leaving the nozzle, a glow or flame at the nozzle, chamber or catalyst bed, or a sudden light at the thruster, even when it is small in the frame or the camera is far away); shutdown is the first later frame in which the firing has stopped. A clip that starts while the thruster is already firing has its ignition at the first frame. Report no ignition or shutdown for any other kind of recording.

Rules: use only the given timestamps; do not interpolate times between frames. Describe what is visible, without causes or guesses. Never describe people: describe a hand or a tool only by what it does to the hardware.
--- user ---
Folder and file: $folder_context
Duration: $duration_s s. Sound: $has_audio.
Files next to it: $nearby_files
How the frames were picked: $frame_plan
The frames follow, each after its timestamp.
