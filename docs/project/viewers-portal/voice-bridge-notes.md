# TeamWatch: push-to-talk voice bridge

Discussion notes saved on 26 October 2026.

**Status:** Proposed design. These notes describe the voice feature discussed in
chat; they do not mean that voice communication has been implemented.

## Objective

Add live group conversation alongside the synchronized movie and its audio.
Microphones should transmit only while the participant holds a talk button.
Multiple participants must be able to speak at the same time.

Example: a host and three participants watch together. When one person speaks,
the other three hear them. When two speak simultaneously, each hears the other,
and the remaining two listeners hear both. Participants do not receive their own
microphone stream back.

## Requested experience

- Ask for a display name when someone joins the room.
- Let the host enable or disable voice communication for the room.
- Participants tap **Join voice** once to enable listening and establish their
  voice connection.
- A **Hold to talk** button activates the microphone only while held.
- The movie continues playing while conversation audio plays alongside it.
- Show a small white-text speaker line, such as **Gokul is speaking** or
  **Gokul and Arun are speaking**.
- Offer independent movie and voice volume controls.
- Optionally lower movie volume while people speak, restoring it afterward.
- Keep projector/video-only devices silent by default; voice listening should be
  an explicit choice if enabled on such a device.

## Architecture options

### 1. Peer-to-peer mesh

Every device sends its audio directly to every other device, possibly through
TURN relays when necessary.

With four participants there are six pairwise peer connections. Each active
speaker sends three copies of their audio. This is workable for a small prototype,
but client upload bandwidth and connection management grow with the group.

### 2. SFU: Selective Forwarding Unit — recommended

Each speaker uploads their audio once to a media server. The server forwards that
track to the other participants, whose browsers play the received tracks together.
The server does not need to decode and mix all voices into one stream.

Projects considered: **LiveKit**, **mediasoup**, and **Janus**.

**Recommendation:** Self-host LiveKit alongside the existing Python application.
Its room management, browser SDK, track controls, permissions, and speaker events
reduce the amount of custom WebRTC infrastructure we need to build.

### 3. MCU: Multipoint Control Unit

The server decodes and mixes participants' voices, then sends a combined audio
stream to each listener, excluding that listener's own voice as appropriate.

This reduces the number of streams clients receive, but requires more server
processing. It is unnecessary complexity for the current small-group use case.

## Recommended responsibilities

### Existing Python application

- Validate room access and host/viewer roles.
- Store the room's voice-enabled setting.
- Associate display names with unique device/participant identities.
- Issue signed, room-scoped media access tokens.
- Enforce host-controlled transmission permissions through server-side media
  permissions, including existing participants when voice is disabled.
- Continue handling movie play/pause, seeking, synchronization, and download-ahead.

A name is a display label, not an authentication credential. Two devices may have
similar names but must have distinct participant identities.

### LiveKit / WebRTC

- Carry real-time microphone audio separately from movie delivery.
- Publish and subscribe to individual participants' audio tracks.
- Forward simultaneous speakers' tracks to the other participants.
- Expose active-speaker events for the speaker-name line.

### Browser

- Keep the voice connection established while no microphone track is transmitting.
- Handle microphone permissions and push-to-talk input.
- Play remote voice tracks alongside the movie audio.
- Render active speaker names safely as text.
- Maintain separate movie and conversation volume settings.

## Microphone lifecycle and privacy

There are two choices:

1. **Fast activation:** Acquire the microphone once and keep its track muted
   between presses. This avoids repeated capture startup, but microphone capture
   may remain acquired even while no speech is transmitted.
2. **Capture only while held:** Acquire and publish a microphone track on press;
   unpublish and stop it on release. The next press acquires a new track.

**Recommended for the stated requirement:** Capture only while held. Show a clear
**Microphone ready—talk now** indicator because permission/capture startup can
introduce a short delay.

Stopping this application's microphone track does not revoke the browser's saved
permission or stop a different tab that is independently using the microphone.

Stop transmission on release, pointer/touch cancellation, focus loss, page exit,
room disconnection, or the host disabling voice.

Acquisition is asynchronous: if someone releases the button before permission or
capture finishes, immediately stop the late-arriving track instead of publishing
it. A delayed acquisition must never leave the microphone live after release.

## Simultaneous speakers

Push-to-talk is a microphone activation policy, not a one-speaker-at-a-time lock.
The requested bridge allows overlapping speakers. Do not add a walkie-talkie-style
exclusive speaking slot unless that becomes a separate product requirement.

Use active-speaker detection to distinguish actual speech from someone holding a
button silently. Button-held status can be shown separately if useful.

## Keep voice independent of movie synchronization

- Movie media uses the current cached/downloaded playback path and shared timeline.
- Conversation uses a separate real-time WebRTC path.
- The browser combines the audible outputs; we do not re-encode the movie to add
  live voices.
- Do not apply the movie's playback-rate corrections or seek operations to voice.
- Voice buffering/disconnection must not trigger the existing movie-buffering
  global pause rule. Otherwise a brief voice-network issue could stop the movie.
- Movie playback and voice participation need separate readiness/presence states.

## VPS implications

Add LiveKit as a Docker service with its own secrets and configuration. Reuse the
existing application for authentication and room controls.

HTTPS/signaling routing and media-network connectivity are different concerns.
Nginx's normal HTTP reverse proxy configuration alone is not sufficient for every
WebRTC media path. Configure the selected WebRTC UDP/TCP ports and TURN support
without conflicting with existing VPS services.

- **Signaling:** Exchanges connection setup and control information.
- **ICE:** Finds and selects a usable network path.
- **STUN:** Helps discover connectivity/address candidates.
- **TURN:** Relays media when network restrictions prevent a usable direct path.

LiveKit has TURN support; a separate coturn deployment is another option if needed.
Choose the exact deployment configuration after checking existing ports, TLS,
firewall rules, and the expected participant count.

## Suggested implementation sequence

1. Add join names and unique participant identities.
2. Add the host's room-wide voice setting and backend authorization.
3. Set up a test LiveKit deployment and issue room-scoped access tokens.
4. Add voice listening and press-and-hold microphone capture with release guards.
5. Add speaker names, separate volume controls, and optional movie ducking.
6. Test overlapping speakers, rapid press/release, permission denial, host disable,
   reconnects, and Safari/iPhone behavior during simultaneous movie playback.
7. Deploy to the testing environment before promoting to production.

## Interview explanation

> We separate synchronized movie playback from real-time conversation. Python
> handles authentication and room control, while WebRTC transports voice through
> an SFU. Push-to-talk gates microphone capture. The SFU forwards individual
> speaker tracks, and each client mixes remote voices with movie audio. This
> supports simultaneous speakers without continuously transmitting microphone
> audio.

Points to explain in a follow-up:

- Why an SFU avoids the growing upload fan-out of a mesh.
- How SFU forwarding differs from MCU mixing.
- Why live voice should not use the movie's download-ahead pipeline.
- How signaling differs from media transport.
- Why STUN and TURN are necessary across different networks.
- Why a muted track and a stopped track have different capture lifecycles.
- How release-before-permission-completes races are prevented.
- Why display names must not determine authorization.

## References

- [LiveKit SFU](https://docs.livekit.io/reference/internals/livekit-sfu/)
- [LiveKit authentication](https://docs.livekit.io/frontends/build/authentication/)
- [Publishing microphones and muting tracks](https://docs.livekit.io/transport/media/publish/)
- [Subscriptions and active-speaker events](https://docs.livekit.io/transport/media/subscribe/)
- [LiveKit ports and firewall configuration](https://docs.livekit.io/transport/self-hosting/ports-firewall/)
- [WebRTC peer connections, signaling, and ICE](https://webrtc.org/getting-started/peer-connections)
- [TURN servers](https://webrtc.org/getting-started/turn-server)
- [Stopping a microphone track](https://developer.mozilla.org/en-US/docs/Web/API/MediaStreamTrack/stop)
