# Media Preparation Performance Discussion

Date: 19 November 2026

Status: discussion and proposed improvements; no encoding configuration changes or performance benchmarks were made as part of this discussion.

## Reported observation

The host reported that a 3 GB movie lasting 2 hours 57 minutes produces approximately 4 seconds of playable media every 2 seconds of processing. This corresponds to **2× real-time preparation speed**. The host wants to reduce the wait and asked whether 4× or 8× is achievable.

File size alone does not explain preparation speed. Source codec, resolution, frame rate, audio tracks, available CPU, storage and server load can affect it. The specific movie's codec and runtime conversion log have not been inspected, so its bottleneck remains unconfirmed.

## Current implementation

The code inspected during the discussion uses:

- A copy path for H.264 video with `yuv420p` pixels, up to 1920×1080, avoiding video re-encoding.
- CPU conversion for other video using `libx264`, the `veryfast` preset, CRF 23 and a hardcoded limit of 2 encoding threads. Conversion scales within 1080p and outputs 30 fps.
- Copying for compatible AAC-LC audio; other audio is converted to AAC.
- HLS segments targeting 4 seconds and an initial readiness threshold of 8 seconds of prepared media.
- Full upload before preparation begins, with one global preparation job running at a time.

References: [media pipeline](../../../media_pipeline.py), [application readiness logic](../../../app.py), [episode scheduler](../../../episode_library.py).

## Starting playback versus finishing preparation

Full preparation is not required to start watching. At a sustained 2× rate, generating the initial 8 seconds would take approximately 4 seconds of processing, plus probing, encoder startup and segment-publication overhead. Upload time and time waiting for another preparation job are additional.

At normal 1× playback speed, sustained 2× preparation should grow the prepared lead. This does not guarantee uninterrupted playback: conversion can slow down, participants can have network/device buffering issues, and seeking beyond the prepared portion can stall.

The host must explicitly select the episode and start playback. “Ready to start” and “Fully prepared” should remain distinct, and prepared duration should remain separate from each participant's downloaded buffer. An 8-second readiness threshold is not a guarantee of smooth playback for the entire movie.

## Target speeds and estimated completion times

For a 177-minute movie, assuming a constant rate and excluding upload, queueing and startup overhead:

- **2×:** 88 minutes 30 seconds for complete preparation.
- **4×:** 44 minutes 15 seconds.
- **8×:** 22 minutes 7.5 seconds.

These are arithmetic estimates, not measured results or promised service levels. The objective is to increase preparation speed and reduce preparation time.

## Proposed improvements

1. **Make the encoding thread limit configurable.** Benchmark higher values against the server's actual CPU allocation while preserving capacity for active viewers. Doubling threads does not imply double throughput.
2. **Benchmark a faster preset.** Compare `superfast` with the current `veryfast`. Faster presets generally trade compression efficiency for speed, potentially increasing output size and delivery bandwidth at comparable quality; inspect both quality and size.
3. **Offer an optional 720p conversion mode.** This reduces encoding work at the cost of resolution. Preserve the existing compatible-video copy path.
4. **Evaluate hardware encoding when available.** A supported GPU encoder may improve throughput, but requires suitable hardware, drivers, FFmpeg support and container access. Availability on the production host is unconfirmed.
5. **Prefer compatible sources where practical.** H.264/AAC input can avoid expensive conversion. The application already uses a compatible-video copy path; it is not a new optimization to enable universally.

FFmpeg describes stream copying as bypassing decoding and encoding, making it fast without encoding-related quality loss: [official FFmpeg documentation](https://www.ffmpeg.org/ffmpeg.html#Streamcopy).

## Suggested next implementation and validation

First inspect the movie's stream metadata, conversion log, copy/transcode status, server CPU allocation and resource usage. Separate time spent uploading, queueing, preparing and buffering before choosing an optimization.

Then make thread count and preset configurable, retaining current defaults until measured alternatives are validated. Compare the same representative section of the same source on the target server, changing one setting at a time. Record preparation speed, time to first playable segments, CPU and memory usage, output size, visual quality and active-viewer playback behavior. Follow a short benchmark with a full-length run to verify sustained performance.

Aim for 4× first; evaluate 8× based on measured hardware capacity and acceptable quality/storage trade-offs. Do not guarantee either speed for every file. No hardware purchase, deployment or configuration change was approved or performed in this discussion.
