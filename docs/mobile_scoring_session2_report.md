# Mobile Scoring Revival - Session 2 Report

## Date: March 9, 2026

## Goal
Restore mobile phone scoring (JMCS - Just Dance Mobile Controller System) in Just Dance 2021 PC by bypassing defunct Ubisoft server dependencies and running a local mock server.

## Current State
- **Error popup**: SUPPRESSED (Patch Q blocks all TRC messages)
- **Game behavior**: Launches, connects to mock server, authenticates, fetches parameters, then **does nothing** (stuck on a blank/loading screen)
- **No crash**: The game runs stably with all 14 patches applied
- **Root cause of "does nothing"**: The online features availability check (`checkOnlineFeaturesAvailable`) still FAILS internally. The TRC error popup is suppressed, but the game's boot sequence is stuck waiting for online features to report success before proceeding to the main menu.

## Summary of Work Done

### Session 1 (Previous)
- Discovered the game's binary is a native x64 C++ debug build with PDB/MAP files
- Created the mock HTTPS server (ECDSA P-256 certs for TLS 1.3 compatibility)
- Applied SSL bypass patches (A, B, C)
- Game connected to mock server but showed "Ubisoft server error"

### Session 2 (This Session)
1. **Created automated binary patcher** (`patcher.py`) - reads original exe, applies all patches, writes patched exe
2. **Identified the S2S subscription error system** and patched it (D, E, F, I, J)
3. **Discovered that `displayErrorPopup` (Patch K) was NOT the source** - the error comes from the TRC (Technical Requirements Checklist) system
4. **Found the TRC error pipeline**: `checkOnlineFeaturesAvailable` -> `AvailabilityTask` -> failure -> `addOnlineErrorMessage` -> TRC popup (error 502 = `Net_UbiServerConnectionError`)
5. **Fixed a VA calculation bug**: Patches L/M had VAs off by `0x1000` (used map offset as RVA instead of adding section base). Was patching mid-instruction, causing crashes.
6. **Blocked the entire TRC message pipeline** (Patches O, P, Q) - no TRC messages can be queued at all

## All Patches (14 Active)

### VA Calculation Formula
```
Map entry format:  SECTION:OFFSET
For section 0001 (.text):  VA = 0x140001000 + OFFSET
PE Image Base: 0x140000000
.text section: virt_addr=0x1000, raw_ptr=0x400
File offset = 0x400 + OFFSET
```

**IMPORTANT**: The map file shows `section:offset_within_section`. The VA in the rightmost column of the map file is the correct VA. Always verify against the VA column.

### SSL/Session Bypass
| Patch | Function | VA | Bytes | Effect |
|-------|----------|-----|-------|--------|
| A | isSessionValid assert | Auto-found via string search | `EB` (je->jmp) | Skips session validity assert |
| B | certVerifyCallback | `0x1416D3CE0` | `B8 01 00 00 00 C3` | SSL cert pinning returns 1 (accept) |
| C | ssl_verify_cert_chain | `0x141498530` | `B8 01 00 00 00 C3` | CA chain verify returns 1 (accept) |

### Subscription/S2S Error Suppression
| Patch | Function | VA | Bytes | Effect |
|-------|----------|-----|-------|--------|
| D | showS2SServerError | `0x14028E730` | `31 C0 C3` | Returns false (don't show) |
| E | enableS2SErrorPopupDisplay | `0x1406E34C0` | `C3` | Ret immediately |
| F | enableS2SErrorDisplayAfterSubscriptionRefresh | `0x1406E3380` | `C3` | Ret immediately |
| I | RefreshSubscriptionInfoTask::start | `0x14092BE80` | `C3` | Never starts HTTP request |
| J | refreshUserSubscription | `0x14092BD60` | `C3` | Returns immediately |

### Generic Error Popup
| Patch | Function | VA | Bytes | Effect |
|-------|----------|-----|-------|--------|
| K | displayErrorPopup | `0x14071FC40` | `C3` | ALL generic error popups suppressed |

### TRC Error System (The Real Error Source)
| Patch | Function | VA | Bytes | Effect |
|-------|----------|-----|-------|--------|
| L | buildGameplayMessage (JD override) | `0x1400E5060` | `31 C0 C3` | Returns NULL |
| M | buildMessageFromConfig | `0x1400E51F0` | `31 C0 C3` | Returns NULL |
| O | addOnlineErrorMessage | `0x140BE0690` | `C3` | Online errors blocked from TRC |
| P | addGameplayMessage | `0x140BE03F0` | `C3` | Gameplay TRC messages blocked |
| Q | addMessage | `0x140BE0500` | `C3` | ALL TRC messages blocked |

### Skipped Patches (Would Crash)
| Patch | Function | VA | Reason |
|-------|----------|-----|--------|
| G | getSessionError | - | Returns `OnlineError` by value; MSVC x64 ABI uses hidden RDX pointer. `xor eax,eax;ret` corrupts caller's return buffer. |
| H | getSessionStatus | - | Unknown correct enum value; complex stack setup |
| N | checkOnlineFeaturesAvailable | `0x1403240B0` | Boot sequence depends on async task state being initialized by this function. `ret` leaves task uninitialized -> null pointer crash. |

## Key Architecture Findings

### Online Features Boot Sequence Flow
```
JD_GameModule_BootSequence::setupNodesFlow()
  -> JD_OnlineFeatures::checkOnlineFeaturesAvailable()  [0x1403240B0]
     -> Creates AvailabilityTask
        -> AvailabilityTask::start()  [0x1403250B0]
           -> Registers success/failure handlers via Future<bool, OnlineError>
           -> handleNextFeature()  [0x1403243B0]
              -> Iterates through JD_OnlineFeature_Base objects
              -> Each feature checked via Future with callbacks

     ON SUCCESS:
        -> onAvailabilitySuccess()  [0x140324B40]
        -> onFeaturesAvailable()  [0x140324CC0]
        -> onEnsureAllAvailabilitySuccess()  [0x140324BD0]
        -> Boot sequence continues to main menu

     ON FAILURE:
        -> onAvailabilityFailure()  [0x140324B30]
        -> onEnsureAllAvailabilityFailure()  [0x140324B50]
        -> TRCManagerAdapter::addOnlineErrorMessage()  [0x140BE0690]
        -> TRC popup displayed (error 502)
        -> Game stuck (won't proceed past error)
```

### TRC Message Pipeline
```
Error source (e.g., online feature check fails)
  -> addOnlineErrorMessage()  [0x140BE0690]  <-- PATCHED (Patch O)
     -> addGameplayMessage()  [0x140BE03F0]  <-- PATCHED (Patch P)
        -> addMessage()  [0x140BE0500]  <-- PATCHED (Patch Q)
           -> internal_newMessageProcess()  [0x140BE1780]
              -> internal_update_messages()  [0x140BE19D0]
                 -> internal_canDisplayMessage()  [0x140BE15E0]
                    -> internal_showCurrentMessage()  [0x140BE1910]
                       -> internal_openUIManagerMessage()  [0x140BE18D0 / 0x1400E7D00]

Message content built by:
  -> buildGameplayMessage()  [0x1400E5060]  <-- PATCHED (Patch L)
     -> buildMessageFromConfig()  [0x1400E51F0]  <-- PATCHED (Patch M)
```

### The "Does Nothing" Problem
The game suppresses the error popup but the boot sequence is **still stuck** because:
1. `checkOnlineFeaturesAvailable` creates an async task
2. The task checks online features and FAILS (mock server doesn't serve whatever it checks)
3. `onEnsureAllAvailabilityFailure` is called
4. The failure sets internal state that prevents the boot sequence from advancing
5. Without the TRC popup (which had an "OK" button whose callback would have set the game to a recoverable state), the game just sits there

### MSVC x64 ABI Notes
- Functions returning objects by value (not pointers): caller allocates buffer, passes pointer in RDX. Function writes to RDX buffer and returns the pointer in RAX. Stubbing with `xor eax,eax; ret` does NOT write the buffer -> caller reads garbage -> crash.
- Functions returning `bool`, `int`, enums: return value in EAX. Safe to stub with `xor eax,eax; ret` (returns 0/false) or `mov eax, 1; ret`.
- `void` functions: safe to stub with `ret` (C3) as long as they don't set up critical state.
- Virtual functions: patching the implementation is fine; vtable dispatch still works.

## Key Files

| File | Purpose |
|------|---------|
| `jd21/engine/ua_engine.exe` | Original game binary (54MB, x64 debug build) |
| `jd21/engine/ua_engine_patched.exe` | Patched output |
| `jd21/engine/ua_engine.map` | Linker map file (~200MB) with all symbols |
| `MobileScoringRevivalProject/patcher.py` | Automated binary patcher |
| `MobileScoringRevivalProject/mock-server/server.js` | Mock Ubiservices HTTPS server v4.1 |
| `docs/MOBILE_SCORING_RESTORATION.md` | Session 1 documentation |
| `jd21/data/EngineData/GameConfig/trc_error_list.ilu` | TRC error code definitions |
| `jd21/data/EngineData/GameConfig/popups.ilu` | Popup template configuration |
| `jd21/data/EngineData/GameConfig/localisationTRC.isg` | TRC error localized text |

## Mock Server State (v4.1)
- **Ports**: 80 (HTTP), 443 (HTTPS+WSS), 12000 (GAAP dual HTTP/HTTPS), 11046+11048 (Bloomberg)
- **Cert**: ECDSA P-256 self-signed (TLS 1.3 only - game's OpenSSL doesn't support RSA-PSS or TLS 1.2)
- **Handled endpoints**:
  - `POST /v3/profiles/sessions` - Authentication (returns session ticket)
  - `GET /v1/applications/{appId}/parameters` - Returns 60 app-level parameters
  - `GET /v1/spaces/{spaceId}/parameters` - Returns 112 space-level parameters
  - `GET /v1/applications/{appId}/configuration` - App configuration
  - Various subscription, policy, profile endpoints
- **Game identifiers**:
  - App ID: `c8cfd4b7-91b0-446b-8e3b-7edfa393c946`
  - Space ID: `24981c05-65a2-4d47-b5ba-8b38c6f3e62d`

## Hosts File Redirects
All in `C:\Windows\System32\drivers\etc\hosts` pointing to `127.0.0.1`:
- `public-ubiservices.ubi.com`
- `public-ws-ubiservices.ubi.com`
- `gaap.ubiservices.ubi.com`
- `gamecfg-mob.ubi.com`
- `jd.ubisoft.com`
- `v2.phonescoring.jd.ubisoft.com`
- (and others)

## TRC Error System Details

The error 502 (`Net_UbiServerConnectionError`) is:
- Defined in `trc_error_list.ilu` as `Net_UbiServerConnectionError = 502`
- Hardcoded in C++ to use popup template `menu1ButtonLeftAlignmentSoundNetworkError` (the `associateErrorList` in `popups.ilu` is empty - binding is in engine code)
- Localized text: Title="Ubi Servers Error", Message="The Ubisoft servers are currently not available", Button="OK"
- Triggered by `JD_OnlineFeatures::checkOnlineFeaturesAvailable()` during boot

## Ideas for Next Session

### Priority 1: Make the boot sequence succeed (fix "does nothing")
The game needs the online features availability check to SUCCEED, not just suppress its error. Options:

1. **Patch `onEnsureAllAvailabilityFailure` to call `onEnsureAllAvailabilitySuccess` instead**
   - `onEnsureAllAvailabilityFailure` at `0x140324B50`
   - `onEnsureAllAvailabilitySuccess` at `0x140324BD0`
   - Could rewrite the first few instructions to jump to the success handler
   - Risk: success handler may expect state that was set during actual success

2. **Patch `onAvailabilityFailure` to call `onAvailabilitySuccess`**
   - Failure: `0x140324B30`, Success: `0x140324B40`
   - These are very close in address - success is only +0x10 from failure
   - Could potentially just jump to success

3. **Find what features are checked and serve them from mock server**
   - `handleNextFeature` iterates through `JD_OnlineFeature_Base` objects
   - Need to find what HTTP requests it makes and add them to mock server
   - Look for feature names/URLs in the binary near the OnlineFeatures code
   - Check mock server logs for any additional requests we're not handling

4. **Patch `CheckOnlineFeaturesAvailableTask::update` to force success**
   - At `0x140325500` - this is the task update loop
   - Could potentially force it to return a "done successfully" state

5. **Patch `IsOnlineTask::onPingFailure` to call `onPingSuccess`**
   - Failure: `0x140324EC0`, Success: `0x140324ED0`
   - Very close addresses again - success is only +0x10 from failure
   - The ping task likely checks if Ubi servers are reachable

6. **Try the debug menu skip**: `DebugMenuEntrySkipUplayLogin::onSelect` at RVA `0x005524e0` (VA `0x1405534E0`)
   - This debug menu option might skip the entire online check

### Priority 2: JMCS Session Creation
Once past the boot screen, the game needs to create a JMCS session:
```
startCreatingJMCSSession
  -> Task_CreateJMCSSession_Ubiservices (HTTP POST)
  -> onJMCSSessionCreationSuccess
  -> HttpHelper::setJMCSSessionId
  -> JD_GS_UIConnectPhone::setPairingCode
```
- Need to find the JMCS session endpoint URL and add it to mock server
- Need to understand the pairing code format

### Priority 3: WebSocket Phone Connection
After pairing code is displayed, phones connect via WebSocket to `public-ws-ubiservices.ubi.com:443`

## Important Map File Symbols for Next Session

### Online Features (highest priority)
```
checkOnlineFeaturesAvailable        0001:003230b0  VA 0x1403240B0
ensureAllAvailability               0001:003231e0  VA 0x1403241E0
AvailabilityTask::start             0001:003240b0  VA 0x1403250B0
AvailabilityTask::handleNextFeature 0001:003233b0  VA 0x1403243B0
AvailabilityTask::onFeaturesAvailable        0001:00323cc0  VA 0x140324CC0
AvailabilityTask::onAvailabilityFailure      0001:00323b30  VA 0x140324B30
AvailabilityTask::onAvailabilitySuccess      0001:00323b40  VA 0x140324B40
IsOnlineTask::onPingFailure         0001:00323ec0  VA 0x140324EC0
IsOnlineTask::onPingSuccess         0001:00323ed0  VA 0x140324ED0
CheckOnlineFeaturesAvailableTask::update     0001:00324500  VA 0x140325500
JD_OnlineFeatures::onEnsureAllAvailabilityFailure  0001:00323b50  VA 0x140324B50
JD_OnlineFeatures::onEnsureAllAvailabilitySuccess  0001:00323bd0  VA 0x140324BD0
JD_OnlineFeatures::init             0001:003235f0  VA 0x1403245F0
JD_OnlineFeatures::update           0001:00324590  VA 0x140325590
JD_OnlineFeatures::onEvent          0001:00323c10  VA 0x140324C10
```

### TRC Manager (reference)
```
addOnlineErrorMessage               0001:00bdf690  VA 0x140BE0690
addGameplayMessage                  0001:00bdf3f0  VA 0x140BE03F0
addMessage                          0001:00bdf500  VA 0x140BE0500
internal_buildAndAddMessage_commonHelper  0001:00be02e0  VA 0x140BE12E0
checkPopupBuild                     0001:000e45d0  VA 0x1400E55D0
hasError                            0001:00be0260  VA 0x140BE1260
isDisplayingError                   0001:00be0e40  VA 0x140BE1E40
update (JD override)                0001:000e7760  VA 0x1400E8760
update (engine base)                0001:00be1be0  VA 0x140BE2BE0
```

### Debug Menu (potential shortcut)
```
DebugMenuEntrySkipUplayLogin::onSelect  RVA 0x005524e0  VA 0x1405534E0
```

### JMCS (for later)
```
startCreatingJMCSSession            (search map file)
Task_CreateJMCSSession_Ubiservices  (search map file)
onJMCSSessionCreationSuccess        (search map file)
HttpHelper::setJMCSSessionId        (search map file)
JD_GS_UIConnectPhone::setPairingCode (search map file)
```

---

## Companion App Analysis (Just Dance 2015 Companion v8.0.2-54)

Decompiled APK located at:
`MobileScoringRevivalProject/com.ubisoft.dance.justdance2015companion_8.0.2-54_minAPI26(arm64-v8a,armeabi-v7a)(nodpi)_apkmirror.com.apk_Decompiler.com/`

### Critical Architecture Finding

**This is a Unity IL2CPP application.** The Java sources are just a thin Android platform layer. All core game logic -- WebSocket connections, JMCS pairing, scoring algorithms, sensor data transmission -- is compiled into native ARM code in `libil2cpp.so`. The Java layer provides only:
- Android OS integration (sensors, network, activities)
- PlayStation Companion Util library (PS4-only discovery/pairing)
- Ubisoft push notification plumbing (Houston services)
- Firebase/Ubiservices authentication bridging

**No WebSocket URLs, JMCS code, pairing code format, or scoring protocol were found in the Java sources.** All of that is in the IL2CPP binary.

### Key DLLs Compiled into libil2cpp.so

From `resources/assets/bin/Data/ScriptingAssemblies.json`:
- `Assembly-CSharp.dll` -- Main game logic (scoring, pairing, sensor data, WebSocket)
- `UbiservicesApi_ANDROID.dll` -- Ubisoft services API
- `Newtonsoft.Json.dll` -- JSON serialization (confirms JSON is the message format, not protobuf)
- `PluginForWP.dll` -- Platform plugin (may contain WebSocket/scoring protocol)
- `Ubisoft.Orion.Orbit.dll` -- Ubisoft telemetry

### IL2CPP Metadata Location (for future reverse engineering)

To extract C# class/method names from the native binary, run **Il2CppDumper** on:
- Binary: `resources/lib/arm64-v8a/libil2cpp.so`
- Metadata: `resources/assets/bin/Data/Managed/Metadata/global-metadata.dat`

Search the dumped output for classes related to: `PhoneScoring`, `AccelData`, `SensorManager`, `WebSocket`, `JMCS`, `PairCode`, `MapName`, `GameState`, `DanceMove`

### Useful Findings from Java Layer

#### 1. Accelerometer is the ONLY Required Sensor

From `AndroidManifest.xml`:
```xml
<uses-feature android:name="android.hardware.sensor.accelerometer" android:required="true"/>
```
- Gyroscope is NOT listed as required
- Accelerometer data is measured in **G-force units** (converted by dividing raw m/s^2 by 9.80665)
- Source: `sources/com/ubisoft/justdance/phone/devicecaps/AccelerometerCaps.java`

```java
public float getAccelerometerMaxRange() {
    return ((SensorManager) this.context.getSystemService("sensor"))
        .getDefaultSensor(1).getMaximumRange() / 9.80665f;
}
```

#### 2. JSON over WebSocket (Not Protobuf)

`Newtonsoft.Json.dll` is included in the Unity assemblies. The only `.proto` files found are for Firebase Cloud Messaging (not game-specific). This confirms the phone-to-game communication uses **JSON messages over WebSocket**.

#### 3. PlayStation 4 Local Discovery Protocol (Reference)

The PS4 pairing path is fully visible in Java and uses a completely different protocol (local UDP/TCP) than PC. This is **not relevant to the PC JMCS WebSocket path** but documents how the companion app works on PS4:

- **UDP Discovery**: Broadcast on port `987` with packet `SRCH * HTTP/1.1\ndevice-discovery-protocol-version:00020020\n`
- **TCP Binary Protocol (OCCP)**: After discovery, connects via TCP with little-endian binary packets
- **Pairing**: PS4 uses 8-char PIN code or 4-digit passcode entered on the phone
- **Session Handshake**: CHello packet (ID 0x6F636370 = "occp", 28 bytes) with version + random seed
- **PS4 Client ID**: `8cf0c395-bef5-49de-9330-0e7265375ec9`
- **PS4 Client Secret**: `BOebri8miu2oav4u`

**Note**: On PC, the pairing goes through the JMCS WebSocket (cloud-based via `wss://public-ubiservices.ubi.com`), NOT local discovery. The PS4 protocol is completely separate.

#### 4. Ubisoft Cloud Config Endpoints

From `sources/ubisoft/mobile/UbimobileToolkit.java`:
- **Cloud config URL**: `http://gamecfg-mob.ubi.com/profile/?`
- **Product ID**: `745` (companion app)
- **Time sync**: `http://gamecfg-mob.ubi.com/profile/?epoch=1` (returns `Server-Time` and `Ubisoft-Zone` headers)
- **Cloud key get**: `?action=game_get&productid=745&deviceuid={UUID}&keys=["{key}"]`
- **Cloud key set**: `?action=game_set&productid=745&deviceuid={UUID}&type="full"&data={"{key}":"{value}"}`

#### 5. Houston Push Notification Endpoints

From `sources/com/ubisoft/orion/pushnotifications/`:
- **Auth**: `https://authentication-{pid}-{env}.houston-services.ubi.com/auth`
- **Devices**: `https://push-notifications-{pid}-{env}.houston-services.ubi.com/devices`
- **User data**: `https://user-data-{pid}-{env}.houston-services.ubi.com/{path}`
- Auth body: `{ "id": "{deviceId}", "lang": "{lang}", "externalAccounts": { ... } }`
- Returns: `AToken`, `userId`, `country`

#### 6. Native Libraries

Located at `resources/lib/arm64-v8a/`:
- `libil2cpp.so` -- ALL compiled C# code (WebSocket, JMCS, scoring, sensor handling)
- `libubiservices.so` -- Ubiservices SDK native bridge (loaded by `JavaInterface.java` via `System.loadLibrary("ubiservices")`)
- `libunity.so` -- Unity engine runtime
- `libmain.so` -- Entry point

### Implications for Next Session

1. **The companion app Java code does NOT reveal the JMCS WebSocket protocol.** The WebSocket connection, message format, pairing exchange, and scoring data transmission are all in `libil2cpp.so`. To extract this, run Il2CppDumper and analyze the results.

2. **JSON is confirmed as the message format** (Newtonsoft.Json is bundled), so when intercepting JMCS WebSocket traffic, expect JSON frames.

3. **Accelerometer-only scoring** (no gyroscope required) -- the phone sends accelerometer data in G-force units. The exact sampling rate and data frame structure are in the IL2CPP binary.

4. **The PC path uses cloud-based JMCS WebSocket** (`wss://public-ubiservices.ubi.com`) -- completely different from PS4's local UDP/TCP discovery. The mock server must handle WebSocket upgrade on port 443 for JMCS.

5. **Key mock server parameters for JMCS** (from session 1/2 parameter responses):
   - `JmcsHost` -- WebSocket URL for JMCS (in `us-sdkClientUrls` group)
   - `SmartphoneServiceUrl` -- Phone scoring service URL
   - `SmartphoneControlAvailable` -- Must be `true`
   - `SmartphoneScoringAvailable` -- Must be `true`
   - `WebsocketUrl` -- Alternative WebSocket URL parameter

---

## Il2CppDumper Analysis (Companion App Native Code)

Il2CppDumper was run on the companion app's `libil2cpp.so` + `global-metadata.dat`, recovering all C# class/method names. Output at:
`MobileScoringRevivalProject/com.ubisoft.dance.justdance2015companion_8.0.2-54_minAPI26(arm64-v8a,armeabi-v7a)(nodpi)_apkmirror.com_dumped/arm64-v8a/`

This reveals the **complete JMCS protocol architecture**.

### Phone-to-Console Connection Flow

```
1. User enters 6-digit pairing code in PairingContent UI
2. ConnectionManager.OnPressPairingScreenValidated(pairingCode)
   -> ConsoleDiscoveringManager.Discover(pairingCode)
      -> Two parallel discovery methods:
         a) UDP LAN broadcast (ConsoleDiscoveryAgentCustomJD)
            - Sends "phonescoring.jd.ubisoft.com" on UDP port 6000
            - Listens for JSON responses on UDP port 7000
            - Response format: {"platform":"%s","titleId":"%s","protocol":"%s"}
         b) JMCS cloud resolution (SessionService.ResolvePairingCode)
            - GET /pairing-info?code={pairingCode}
            - Resolves to ConsoleServer with PairingUrl, TlsCertificate, etc.
3. ConsoleServer selected (from LAN or cloud discovery)
   -> ConsoleNetworkManager.Connect(consoleServer)
      -> Creates WSMsgConnection (WebSocket)
      -> WebSocket connects to console's PairingUrl
4. WebSocket handshake:
   -> SendHello()           // JD_PhoneDataCmdHandshakeHello
   -> ConsoleConnected()    // receives gameVersion, protocolVersion, platformName
   -> SendSync()            // JD_PhoneDataCmdSync
   -> SendEndSync()         // JD_PhoneDataCmdSyncEnd
5. Connected - phone receives UI commands, sends accelerometer data
```

### JMCS API Endpoints

The JMCS service runs at `v1.phonescoring.jd.ubisoft.com` or `v2.phonescoring.jd.ubisoft.com`:

| Endpoint | Purpose |
|----------|---------|
| `/session` | Create JMCS session |
| `/pairing-info?code={code}` | Resolve 6-digit pairing code to console info |
| `/initiate-punch-pairing` | NAT punch-through for firewalled connections |

The `JmcsFacade` class builds requests with:
- `applicationId` (App ID)
- `authorizationHeader` (from Ubiservices session)
- `jmcsSessionId` (created via `/session`)
- `baseUrl` (JMCS host URL)

### WebSocket Message Protocol

Messages are JSON with a `__class` field identifying the message type.

#### Phone -> Console Messages
| `__class` Value | Purpose |
|-----------------|---------|
| `JD_PhoneDataCmdHandshakeHello` | Initial handshake from phone |
| `JD_PhoneDataCmdHandshakeContinue` | Handshake continuation |
| `JD_PhoneDataCmdSync` | Time synchronization |
| `JD_PhoneDataCmdSyncEnd` | Sync completion |
| `JD_PhoneScoringData` | **Accelerometer scoring data** (the main payload) |
| `JD_PhoneUiData` | Phone UI data |
| `JD_PhoneUiSetupData` | Phone UI setup |
| `JD_PhoneUiShortcutData` | Phone UI shortcut |
| `JD_ProfilePhoneUiData` | Profile UI on phone |
| `JD_SimplePhoneUiData` | Simple phone UI |
| `JD_InputCollectionPhoneData` | Input collection from phone |
| `ChangeAction_PhoneCommandData` | Change action command |
| `ChangeItem_PhoneCommandData` | Change item command |
| `ChangeRow_PhoneCommandData` | Change row command |
| `ValidateAction_PhoneCommandData` | Validate action command |
| `JD_SubmitKeyboard_PhoneCommandData` | Keyboard text submit |
| `JD_CancelKeyboard_PhoneCommandData` | Keyboard cancel |

#### Console -> Phone Messages
| `__class` Value | Purpose |
|-----------------|---------|
| `JD_EnableAccelValuesSending_ConsoleCommandData` | **Start sending accelerometer data** |
| `JD_DisableAccelValuesSending_ConsoleCommandData` | **Stop sending accelerometer data** |
| `InputSetup_ConsoleCommandData` | Input/UI setup for phone |
| `JD_EnableLobbyStartbutton_ConsoleCommandData` | Enable lobby start button on phone |
| `EnableCarousel_ConsoleCommandData` | Enable/disable carousel UI |
| `EnablePhoto_ConsoleCommandData` | Enable photo feature |
| `JD_ClosePopup_ConsoleCommandData` | Close popup on phone |
| `JD_NewPhoto_ConsoleCommandData` | New photo notification |
| `JD_OpenPhoneKeyboard_ConsoleCommandData` | Open keyboard on phone |
| `JD_OpenTakeMasterScreen_ConsoleCommandData` | Open take master screen |
| `JD_PlaySound_ConsoleCommandData` | Play sound on phone |
| `JD_TriggerTransition_ConsoleCommandData` | Trigger screen transition |
| `ShortcutSetup_ConsoleCommandData` | Shortcut setup |
| `JD_DisabledScreenPhoneUiData` | Disabled screen UI |

### Accelerometer Scoring Data

The `AccelerometerHandler` class:
- Captures accelerometer data at **50 Hz** (`_sendingFrequency = 50`)
- Queues data as JSON objects (`_accelsDataList` is `Queue<JSON>`)
- Sends batched data with **40ms latency** (`_sendingLatency = 40`)
- Data includes average frequency tracking (`_avgAccelerometerFrequency`)

Key JSON fields in scoring messages:
- `accelData` -- Array of accelerometer samples
- `accelAcquisitionFreqHz` -- Accelerometer capture frequency
- `accelAcquisitionLatency` -- Capture latency
- `accelMaxRange` -- Device accelerometer max range (in G-force)
- `__class` = `JD_PhoneScoringData`

### ConsoleServer Data Model

```csharp
class ConsoleServer {
    string Protocol;           // WebSocket subprotocol
    string PairingCode;        // 6-digit pairing code
    string PairingUrl;         // WebSocket URL to connect to
    string TlsCertificate;     // TLS cert for connection
    ConsoleType Platform;      // PC=6, PS4=2, PS5=3, NX=5, X1=0, etc.
    string TitleId;            // Game title identifier
    string DisplayName;        // Console display name
    bool RequiresPunchPairing; // Whether NAT punch is needed
}
```

Platform enum values:
| Value | Platform |
|-------|----------|
| 0 | Xbox One (X1) |
| 1 | Xbox Series X/S (XScarlett) |
| 2 | PS4 |
| 3 | PS5 |
| 4 | Wii U |
| 5 | Nintendo Switch (NX) |
| 6 | **PC** |
| 7 | Google Stadia (GGP) |

### LAN Discovery Protocol (Alternative to Cloud JMCS)

The `ConsoleDiscoveryAgentCustomJD` class implements local network discovery:

1. **Phone broadcasts** on **UDP port 6000**: sends `phonescoring.jd.ubisoft.com` as identification
2. **Console responds** on **UDP port 7000** with JSON: `{"platform":"%s","titleId":"%s","protocol":"%s"}`
3. Phone validates the response and creates a `ConsoleServer` from it

**This is important for PC**: The PC game binary likely has or could have a UDP listener for LAN discovery on port 6000. Search the PC binary's map file for `phonescoring`, `UDPSocket`, `discovery`, or port 6000/7000.

### WebSocket Subprotocol

The `ProtocolValidator` class validates WebSocket subprotocols:
- `WS_PROTOCOL_ROOT` -- Root protocol string
- `WS_PROTOCOL_PREFIX` -- Protocol prefix
- `WS_PROTOCOL_SUFFIX` -- Protocol suffix
- `WS_PROTOCOL_VERSION` -- Protocol version number
- `WS_PROTOCOL_FULL` -- Full protocol string

The WebSocket connection negotiates a subprotocol during the HTTP upgrade handshake.

### Session Creation Flow (JmcsFacade)

```
SessionService.Refresh()
  -> CreateUser()           // Create anonymous Ubiservices user
  -> CreateSession()        // POST /session to JMCS
     -> JmcsFacade.CreateSession(applicationId, ubiservicesFacade, httpEngine, jmcsUrlOverride)
        -> sets: baseUrl, authorizationHeader, jmcsSessionId
  -> GameSession struct populated with:
     - AuthorizationHeader
     - Name, ProfileId, SessionId, UbiTicket
     - JmcsFacade instance
     - UbiservicesFacade instance
     - PlayerCredentialsMobile
```

### NAT Punch Pairing

When `RequiresPunchPairing` is true:
1. `SessionService.InitiatePunchPairing(pairingCode, localIp, localPort)` is called
2. POST to `/initiate-punch-pairing` with the pairing code, local IP, and port
3. `ConsoleNetworkManager` receives `OnPunch` event with `(ushort localPort, string consoleIP)`
4. The WebSocket library (`WebSocketSharp`) has custom `NatPunchOptions` with `AcceptTimeoutMs` for handling the punch connection

### Key Insights for Next Session

1. **Pairing code is 6 digits** (entered via `PairingContent` with `MAX_DIGIT = 6`)

2. **The PC game likely supports LAN discovery** on UDP ports 6000/7000. Search the PC binary map file for UDP socket creation and the string `phonescoring.jd.ubisoft.com`. If found, we can bypass JMCS cloud entirely and pair directly over LAN.

3. **The WebSocket handshake sequence** is: Hello -> Continue -> Sync -> SyncEnd. The phone sends `JD_PhoneDataCmdHandshakeHello` first with device info (phoneID, protocolVersion, avgAccelerometerFrequency).

4. **Scoring data flow**: Console sends `JD_EnableAccelValuesSending_ConsoleCommandData` to start a dance. Phone starts sending `JD_PhoneScoringData` at 50Hz with `accelData` array. Console sends `JD_DisableAccelValuesSending_ConsoleCommandData` when done.

5. **The mock server needs these JMCS endpoints**:
   - `POST /session` -- Return a JMCS session ID
   - `GET /pairing-info?code={code}` -- Return console connection info (PairingUrl, TlsCertificate, Platform, etc.)
   - `POST /initiate-punch-pairing` -- For NAT punch (may not be needed on localhost)

6. **Connection timeout is 15 seconds** (`_connectionTimeout = 15`)

7. **WebSocket close codes and reasons** are tracked via `CloseEventArgs` with `Code` and `Reason`

8. **The `GameSession` struct** carries: AuthorizationHeader, Name, ProfileId, SessionId, UbiTicket, JmcsFacade, UbiservicesFacade, PlayerCredentialsMobile -- the mock server needs to provide all of these during session creation
