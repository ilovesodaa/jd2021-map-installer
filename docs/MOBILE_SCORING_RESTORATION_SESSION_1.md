# Just Dance 2021 PC - Mobile Phone Scoring Restoration

## Project Goal

Restore the mobile phone scoring functionality (JMCS - Just Dance Mobile Controller System) in a Just Dance 2021 PC development build. The game originally connected to Ubisoft's servers at `public-ubiservices.ubi.com` to authenticate and create JMCS sessions, allowing players to use their phones as motion controllers. Since the servers are offline, we are building a local mock server and patching the binary to bypass SSL/TLS security so the game talks to our local server instead.

---

## Binary Details

- **Executable**: `d:\jd2021pc\jd21\engine\ua_engine.exe` (original, unmodified)
- **Patched binary**: `d:\jd2021pc\jd21\engine\ua_engine_final.exe` (all 3 patches applied)
- **Architecture**: Native 64-bit (x86-64), C++ debug build
- **Symbol files**:
  - PDB: ~308MB (full debug symbols)
  - MAP: `d:\jd2021pc\jd21\engine\ua_engine.map` (~200MB)
- **Preferred base address**: `0x140000000` (ASLR active - rebases each session)
- **Bundled OpenSSL**: Statically linked from `openSSL:ssl_lib.obj` (circa 2020). Does NOT use Windows certificate store.

---

## Three-Layer SSL/TLS Security Architecture

The game has three independent security layers for HTTPS connections. All three must be bypassed:

### Layer 1: Session/Auth Assert (Patch A) - COMPLETE

- **Problem**: `getPairingCode@SessionService_Ubiservices` calls `isSessionValid()` which asserts and crashes when no valid Ubisoft session exists
- **Location**: Find via string search for `isSessionValid` assert message in x64dbg
- **Patch**: Change `je` (jump if equal) to `jmp` (unconditional jump) to skip the assert
- **Effect**: Game no longer crashes when session validation fails

### Layer 2: SSL Certificate Pinning (Patch B) - COMPLETE

- **Problem**: `sslcertificatevalidator.cpp:98` implements certificate pinning that rejects any cert not matching Ubisoft's pinned certificates
- **Location**: Find via string search for `sslcertificatevalidator.cpp` in x64dbg, navigate to the function at that source reference
- **Patch**: At the function entry point, assemble:
  ```asm
  mov eax, 1    ; return true (certificate accepted)
  ret
  ```
- **Effect**: All certificates are accepted as valid (pinning check always passes)
- **Note**: This function has 0 direct XREFs because it's registered as a callback via function pointer through `SSL_CTX_set_verify`, not called directly

### Layer 3: Standard TLS CA Chain Verification (Patch C) - COMPLETE

- **Problem**: Even with pinning bypassed, OpenSSL's standard CA chain verification rejects our self-signed certificate (`tlsv1 alert unknown ca`, alert 48). The game uses its bundled OpenSSL CA bundle, not the Windows certificate store, so installing our cert in Windows Trusted Root has no effect.
- **Location**: Find `ssl_verify_cert_chain` in x64dbg Symbols tab
- **Map file VA**: `0x0000000141498530` (RVA `0x01498530`)
- **Patch**: At the function entry point, assemble:
  ```asm
  mov eax, 1    ; return 1 (chain verified successfully)
  ret
  ```
- **Effect**: All certificate chains are accepted as valid

### How to Apply All Patches

1. Open `ua_engine.exe` in x64dbg (Run as Administrator)
2. Apply Patch A: Search strings for `isSessionValid`, navigate to assert, change `je` to `jmp`
3. Apply Patch B: Search strings for `sslcertificatevalidator.cpp`, navigate to function entry, assemble `mov eax, 1` + `ret`
4. Apply Patch C: Symbols tab, search `ssl_verify_cert_chain`, navigate to entry, assemble `mov eax, 1` + `ret`
5. File > Patch File > Save as `ua_engine_final.exe`

---

## TLS Compatibility Details

The game's bundled OpenSSL has specific TLS requirements that the mock server must satisfy:

### What the Game Supports
- **TLS 1.3 ONLY** - the game's `supported_versions` extension only advertises TLS 1.3 (not TLS 1.2)
- **31 cipher suites** advertised in ClientHello, including:
  - TLS 1.3: `TLS_AES_128_GCM_SHA256` (0x1301), `TLS_AES_256_GCM_SHA384` (0x1302), `TLS_CHACHA20_POLY1305_SHA256` (0x1303)
  - TLS 1.2 (advertised but not usable due to version constraint): ECDHE-RSA-AES256-GCM-SHA384, AES256-SHA, etc.
- **ClientHello version**: 3.3 (TLS 1.2 in record layer, but `supported_versions` extension overrides to 1.3 only)

### What Fails and Why
- **RSA certificates + TLS 1.3**: Fails with `tls_choose_sigalg: no suitable signature algorithm`. The game's old OpenSSL does not advertise RSA-PSS, which TLS 1.3 requires for RSA certs.
- **Forcing TLS 1.2** (`maxVersion: 'TLSv1.2'`): Fails with `no shared cipher`. The game only advertises TLS 1.3 in `supported_versions`, so the server sees no common TLS version.
- **`ALL:@SECLEVEL=0`**: Broken in Node.js v24's OpenSSL 3.x.

### What Works
- **ECDSA P-256 certificate + TLS 1.3**: The `ecdsa_secp256r1_sha256` signature algorithm works with TLS 1.3. This is what the mock server uses.

### Cipher Sniffer Tool
`d:\jd2021pc\mock-server\sniff-ciphers.js` captures the raw TLS ClientHello from the game and decodes all 31 cipher suites. Useful for debugging if TLS issues recur.

---

## Mock Server Setup

### Prerequisites
- Node.js v24+ installed
- Run PowerShell/CMD as **Administrator** (required for port 443)

### Node.js Dependencies
```
cd d:\jd2021pc\mock-server
npm install @peculiar/x509 selfsigned
```

### Hosts File Configuration
File: `C:\Windows\System32\drivers\etc\hosts` (edit as Administrator)

Add these lines:
```
127.0.0.1 public-ubiservices.ubi.com
127.0.0.1 public-ws-ubiservices.ubi.com
```

### Running the Server
```
node d:\jd2021pc\mock-server\server.js
```

The server:
- Generates a fresh ECDSA P-256 self-signed certificate on each startup
- Saves the cert to `d:\jd2021pc\mock-server\mock-ca.crt`
- Listens on `https://0.0.0.0:443`
- Works with TLS 1.3

### Server File
`d:\jd2021pc\mock-server\server.js` - handles these endpoints:
- `POST /v3/profiles/sessions` - Returns mock Ubisoft session (ticket, profileId, sessionId, etc.)
- `GET /v1/applications/{appId}/parameters` - Returns app config parameters (currently empty `[]`)
- `GET /v3/policies/{region}` - Returns mock terms of service
- Catch-all: Logs unknown endpoints with full headers for analysis

---

## Current Status: What Works

1. All three patches applied successfully in `ua_engine_final.exe`
2. Hosts file redirects `public-ubiservices.ubi.com` to `127.0.0.1`
3. TLS 1.3 handshake completes successfully (ECDSA cert)
4. Game makes real HTTPS requests to our mock server:

```
POST /v3/profiles/sessions
  Authorization: Basic VmVuX0pEMjAxNkB1Ymlzb2Z0LmNvbTojSkQyMDE2dWJpNDI=
  Ubi-AppBuildId: BUILDID_324393
  Ubi-AppId: c8cfd4b7-91b0-446b-8e3b-7edfa393c946
  Body: {}

GET /v1/applications/c8cfd4b7-91b0-446b-8e3b-7edfa393c946/parameters
  ?parameterGroups=us-staging,us-sdkClientUrlsPlaceholders,us-sdkClientClub,
   us-sdkClientFeaturesSwitches,us-sdkClientLogin,us-sdkClientUrls,
   us-sdkClientChina,us-sdkClientUplay

GET /v3/policies/US?languageCode=FR&contentFormat=plain
```

5. Game accepts our mock session response without crashing

---

## Current Blocker: JMCS Session Never Created

**Symptom**: When clicking "Mobile" in the game, a "Ubisoft server error" appears. No additional HTTP requests appear in the mock server beyond the initial login/parameters/policies sequence.

**Root Cause (likely)**: The game needs specific parameters from `GET /v1/applications/.../parameters` to discover the JMCS service URL. We currently return an empty parameter list `{ parameters: [] }`. Without the JMCS endpoint URL, the game cannot initiate the `Task_CreateJMCSSession_Ubiservices` flow.

**Alternative causes**:
- The JMCS uses WebSocket (WSS) on `public-ws-ubiservices.ubi.com` which is redirected to 127.0.0.1 but we don't have a WebSocket server
- The session response format may be wrong (the `ubi-sessionid` header doesn't appear on subsequent requests, suggesting the game may not be accepting our session ticket)

---

## Key Map File Symbols for JMCS

From `d:\jd2021pc\jd21\engine\ua_engine.map`:

### SSL/TLS Functions
| Symbol | VA (preferred base) | RVA |
|--------|-------------------|-----|
| `SSL_CTX_set_verify` | `0x00000001414862b0` | `0x014862b0` |
| `SSL_CTX_load_verify_locations` | `0x0000000141485690` | `0x01485690` |
| `SSL_CTX_set_cert_verify_callback` | `0x0000000141485ce0` | `0x01485ce0` |
| `ssl_verify_cert_chain` | `0x0000000141498530` | `0x01498530` |
| `initOpenSSLContext@WebSocketStreamImpl` | `0x0000000101776380` | see note |
| `CreateAndInitializeSslContext@NetSslTransport` | `0x00000001412c24e0` | `0x012c24e0` |

### JMCS Session Lifecycle (in `SessionService_Ubiservices.obj`)
| Symbol | VA | Purpose |
|--------|-----|---------|
| `startCreatingJMCSSession` | `0x00000001408e78a0` | Triggers async JMCS session creation |
| `updateCreatingJmcsSession` | `0x00000001408e98c0` | Polls/ticks the creation task |
| `onJMCSSessionCreationSuccess` | `0x00000001408e6df0` | Success callback - receives `JmcsSessionInfo` |
| `onJMCSSessionCreationFailure` | `0x00000001408e6d00` | Failure callback - receives `OnlineError` |

### JMCS Task (in `Task_CreateJMCSSession_Ubiservices.obj`)
| Symbol | VA | Purpose |
|--------|-----|---------|
| `Task_CreateJMCSSession_Ubiservices::ctor` | `0x000000014097b530` | Constructor, takes `String8` (session ticket?) |
| `Task_CreateJMCSSession_Ubiservices::start` | `0x000000014097b990` | Starts the HTTP POST to create JMCS session |
| `Task_CreateJMCSSession_Ubiservices::update` | `0x000000014097c120` | Polls for completion |

### HTTP Helper
| Symbol | VA | Purpose |
|--------|-----|---------|
| `HttpHelper::setJMCSSessionId` | `0x00000001408cf8c0` | Stores JMCS session ID globally |
| `jmcsSessionId` (global) | `0x00000001431b8fb0` | The stored JMCS session ID string |

### Phone Scoring
| Symbol | Source File | Purpose |
|--------|------------|---------|
| `JD_SmartphoneManager::getJmcsToken` | `JD_SmartphoneManager.obj` | Gets JMCS token per player |
| `JD_SmartphoneManager::phoneScoringActivation` | `JD_SmartphoneManager.obj` | Activates phone scoring |
| `JD_PhoneScoringProtocol` | `JD_PhoneScoringProtocol.obj` | Protocol impl with handshake/sync commands |
| `JD_PhoneScoringData` | `JD_PhoneScoringData.obj` | Scoring data serialization |
| `JD_SmartphoneDataQueue::insertReceivedScoringData` | `JD_SmartphoneDataQueue.obj` | Queues incoming scoring data |

### UI
| Symbol | Source File | Purpose |
|--------|------------|---------|
| `JD_GS_UIConnectPhone::setPairingCode` | `JD_GS_UIConnectPhone.obj` | Shows pairing code on screen |
| `SessionService_Ubiservices::getPairingCode` | `SessionService_Ubiservices.obj` | Gets pairing code from network |

---

## Next Steps (Priority Order)

### 1. Find the JMCS Endpoint URL
The game needs to know where to POST to create a JMCS session. Options:
- **Search the binary** for URL strings containing "jmcs" or session-related paths using x64dbg string search
- **Set a breakpoint** on `Task_CreateJMCSSession_Ubiservices::start` (VA `0x14097b990`) and examine what URL it constructs
- **Search the parameters endpoint**: The `us-sdkClientUrls` parameter group likely contains a JMCS host URL. Need to find out what parameter name the game looks for.

### 2. Populate the Parameters Response
Once we know the parameter names, populate `GET /v1/applications/.../parameters` with the JMCS URL pointing to our local server. Example format:
```json
{
  "parameters": [
    {
      "parameterId": "...",
      "name": "JmcsHost",
      "value": "wss://public-ws-ubiservices.ubi.com",
      "parameterGroup": "us-sdkClientUrls"
    }
  ]
}
```

### 3. Add WebSocket Server
The JMCS likely uses WebSocket (WSS) on `public-ws-ubiservices.ubi.com:443`. The `initOpenSSLContext@WebSocketStreamImpl` symbol confirms WebSocket over SSL. Need to add a WebSocket upgrade handler to the mock server (use the `ws` npm package).

### 4. Implement JMCS Session Flow
Based on map file symbols, the flow is:
1. Game calls `startCreatingJMCSSession` (HTTP POST to create session)
2. Server responds with `JmcsSessionInfo` (session ID, pairing code, etc.)
3. Game calls `onJMCSSessionCreationSuccess` and stores session
4. Game calls `setPairingCode` to display code on screen
5. Phone app connects via WebSocket using the pairing code
6. `JD_PhoneScoringProtocol` handles handshake (`PhoneDataCmdHandshakeContinue`, `SyncStart`, `SyncEnd`)
7. `JD_SmartphoneDataQueue::insertReceivedScoringData` processes phone motion data

### 5. Implement Phone Scoring Protocol
The `JD_PhoneScoringProtocol` class has these command types:
- `JD_PhoneDataCmdHandshakeContinue` - connection handshake
- `JD_PhoneDataCmdSyncStart` - start scoring sync
- `JD_PhoneDataCmdSyncEnd` - end scoring sync

These need to be reverse-engineered from the binary to understand the exact WebSocket message format.

---

## File Inventory

| File | Purpose |
|------|---------|
| `d:\jd2021pc\jd21\engine\ua_engine.exe` | Original unpatched binary |
| `d:\jd2021pc\jd21\engine\ua_engine_final.exe` | Patched binary (Patches A+B+C) |
| `d:\jd2021pc\jd21\engine\ua_engine.map` | Map file with all symbol addresses |
| `d:\jd2021pc\mock-server\server.js` | Mock HTTPS server (ECDSA/TLS1.3) |
| `d:\jd2021pc\mock-server\sniff-ciphers.js` | TLS ClientHello cipher suite sniffer |
| `d:\jd2021pc\mock-server\mock-ca.crt` | Self-signed cert (regenerated each server start) |
| `d:\jd2021pc\mock-server\package.json` | Node.js dependencies |
| `C:\Windows\System32\drivers\etc\hosts` | DNS redirect entries |

---

## Game Identifiers

- **App ID**: `c8cfd4b7-91b0-446b-8e3b-7edfa393c946`
- **Build ID**: `BUILDID_324393`
- **SDK**: `UbiServices_SDK_2020.Release.17_PC64_ansi_static`
- **Auth**: Basic auth (Base64): `VmVuX0pEMjAxNkB1Ymlzb2Z0LmNvbTojSkQyMDE2dWJpNDI=`

---

## Troubleshooting Reference

### "Ubisoft server error" on Mobile click
- Server is running but parameters response is empty. Need to populate JMCS URL in parameters.

### TLS `no suitable signature algorithm`
- Using RSA cert with TLS 1.3. Switch to ECDSA P-256.

### TLS `no shared cipher`
- Trying to force TLS 1.2 but game only supports TLS 1.3. Remove `maxVersion` constraint.

### TLS `unknown ca` (alert 48)
- Patch C not applied. Patch `ssl_verify_cert_chain` entry to `mov eax,1; ret`.

### No requests reaching server
- Check hosts file has `127.0.0.1 public-ubiservices.ubi.com`
- Check server is running on port 443 as Administrator
- Check all three patches are in the same binary (`ua_engine_final.exe`)

### 0 XREFs to sslcertificatevalidator
- Normal. Function is registered as a callback pointer via `SSL_CTX_set_verify`, not called directly.

### Patch A and B in separate files
- Must apply both patches to the same binary. Load `ua_engine.exe` in x64dbg, apply A, then B, then C, then export once.

---

## Chronological Timeline of Attempts

### Phase 1: Game Configuration Mapping

**Goal**: Understand the game's configuration surface before attempting any modifications.

- Explored `data/EngineData/GameConfig/` - found 84+ configuration files in Lua table syntax (`.isg`, `.ilu`) plus JSON files
- Key discovery: `zinput.isg` references `input_menu_smartphone.isg` for phone controller input on all platforms
- `cr_device_selection.ilu` defines the device selection carousel with `ScoringType.Phone` entries
- Searched all 677 matches for "phone" in data files - found extensive UI screens (`phone_ftue/`, `phone_connect/`), texture assets, and input handling
- Searched for server URLs (`ws://`, `wss://`, `ubiservices`, `onlinegaming`) in data files - **zero matches**
- **Conclusion**: Server URLs are not in any configuration file. They are hardcoded in the binary or fetched from Ubisoft's parameters API. No config-file-only solution possible.
- Created `docs/JD21_Configuration_Map.md` documenting all settings

### Phase 2: Binary Analysis and Initial Investigation

**Goal**: Determine the executable type and assess modification approaches.

**Findings**:
- `ua_engine.exe`: 54MB native C++ x86-64 executable (NOT .NET - no decompilation shortcut)
- `ua_engine.pdb`: 308MB PDB debug symbol file - full debug symbols available
- `ua_engine.map`: 200MB linker map file with all function addresses and source file references
- `msvcp100d.dll` present: The "d" suffix confirms this is a **debug build** with debug CRT
- No obfuscation, no packing - standard MSVC debug build

**Map file symbol search** revealed extensive JMCS infrastructure:
- `JD_SmartphoneManager`, `JD_SmartphoneDataQueue`, `JD_PhoneScoringProtocol`
- `JD_SmartphoneEvent_PhoneDataCmdReceived` - smartphone event system
- `PhoneData`, `PhoneUiData`, `JD_PhoneUiSetupData` - phone data structures in `GS_UIPage.obj`
- `SessionService_Ubiservices` - online session adapter layer
- PowerShell `$_` variable mangling caused issues searching the 200MB map file - switched to `findstr`

**User shared the actual assert error** when clicking Mobile in the game:
```
Assert
File: d:\streams\jd_code\jd2021_tu1\src\adapters\onlineadapter_ubiservices\
      sessionservice_ubiservices\sessionservice_ubiservices.cpp(171)
Condition: "isSessionValid()"
Message: "Should have a valid session to get the pairing code"

Call stack:
  SessionService_Ubiservices::getPairingCode (line 173)
  JD_SmartphoneManager::phoneScoringActivation (line 172)
  JD_GSS_UIDeviceSelection_Update::init (line 32)
  JD_GSStateChain::start (line 118)
  JD_GameScreen::changeStatus (line 752)
  ... up through JD_GameManager::update -> ApplicationFramework::update
```

**Analysis**: The game requires a valid Ubisoft online session before it can request a pairing code. The `getPairingCode` function calls `isSessionValid()` which asserts because no Ubisoft session exists. This assert fires when the device selection screen initializes, before the user even clicks "Phone".

**Proposed approach**: Three-layer bypass strategy:
1. Patch the assert to not crash (Patch A)
2. Bypass SSL certificate pinning so game accepts our cert (Patch B)
3. Redirect DNS via hosts file + run mock HTTPS server on localhost

### Phase 3: Applying Patch A (Assert Bypass)

**Goal**: Stop the game from crashing on the `isSessionValid()` assert.

- Found `isSessionValid` string reference in x64dbg
- Navigated to the assert check: a `je` (jump if equal/zero) instruction that skips the assert when the session IS valid
- **Patch A**: Changed `je` to `jmp` (unconditional jump) to always skip the assert
- **User confirmed**: "i patched it, tried running and the assert no longer shows up, good"
- Saved as `ua_engine_patched.exe`

### Phase 4: Applying Patch B (SSL Certificate Pinning Bypass)

**Goal**: Make the game accept any SSL certificate instead of only Ubisoft's pinned certs.

- Searched x64dbg strings for `sslcertificatevalidator.cpp` - found the source reference at line 98
- User had difficulty navigating x64dbg (Screenshots 416-419):
  - Got confused finding the function entry point
  - Couldn't locate `SSL_CTX_set_verify` in `initOpenSSLContext` function
  - Eventually found the right approach: right-click on the instruction → Assemble
- **Patch B**: At the `sslcertificatevalidator` function entry, assembled:
  ```asm
  mov eax, 1    ; return true (all certs accepted)
  ret
  ```
- **Important lesson**: This function has 0 XREFs in x64dbg because it's registered as a callback via function pointer through `SSL_CTX_set_verify`, not called directly
- User: "nevermind, i had to right click then click assembler, i did it now"

**Mistake**: Patches A and B were initially saved to separate files (`ua_engine_patched.exe` and `ua_engine_patched2.exe`). Both patches must be in the same binary. Re-applied both patches to one file.

### Phase 5: Mock Server Setup and TLS Debugging

**Goal**: Set up a local HTTPS server that the game would connect to instead of Ubisoft's servers.

**Step 1: DNS Redirect**
- Added to `C:\Windows\System32\drivers\etc\hosts`:
  ```
  127.0.0.1 public-ubiservices.ubi.com
  127.0.0.1 public-ws-ubiservices.ubi.com
  ```

**Step 2: Initial Mock Server (RSA cert)**
- Created `mock-server/server.js` with Node.js HTTPS server on port 443
- Used `selfsigned` npm package to generate RSA self-signed certificate
- **FAILURE 1**: `tls_choose_sigalg: no suitable signature algorithm`
  - **Cause**: TLS 1.3 requires RSA-PSS for RSA certificates, but the game's old OpenSSL (circa 2020) doesn't advertise RSA-PSS in its ClientHello signature algorithms

**Step 3: Attempted TLS 1.2 Fallback**
- Tried forcing server to `maxVersion: 'TLSv1.2'`
- **FAILURE 2**: `no shared cipher`
  - **Cause**: The game's `supported_versions` extension only advertises TLS 1.3. When the server tries TLS 1.2, there's no version overlap.

**Step 4: Attempted Cipher Suite Relaxation**
- Tried setting `ciphers: 'ALL:@SECLEVEL=0'` on the Node.js server
- **FAILURE 3**: Broken/not effective in Node.js v24's OpenSSL 3.x

**Step 5: Built Cipher Sniffer Tool**
- Created `mock-server/sniff-ciphers.js` - a raw TCP server that captures the TLS ClientHello bytes and decodes all cipher suites
- **Discovery**: Game advertises 31 cipher suites in ClientHello:
  - 3 TLS 1.3 suites: `TLS_AES_128_GCM_SHA256` (0x1301), `TLS_AES_256_GCM_SHA384` (0x1302), `TLS_CHACHA20_POLY1305_SHA256` (0x1303)
  - 28 TLS 1.2 suites (not usable because `supported_versions` locks to TLS 1.3)
  - ClientHello record layer says TLS 1.2 (0x0303), but `supported_versions` extension overrides to TLS 1.3 only
- **Key insight**: The game CAN do TLS 1.3 - the issue was only with RSA certificates

**Step 6: ECDSA Certificate (Success)**
- Switched to ECDSA P-256 certificate using `@peculiar/x509` npm package
- `ecdsa_secp256r1_sha256` is in the game's advertised signature algorithms
- **TLS handshake succeeded!** Game connected to mock server.

**Step 7: Unknown CA Error**
- TLS handshake completed but game sent `tlsv1 alert unknown ca` (alert 48) and closed connection
- **Cause**: Even with Patch B (pinning bypass), OpenSSL's standard CA chain verification (`ssl_verify_cert_chain`) still rejects our self-signed cert because it's not in the bundled CA store
- Attempted to install our cert in Windows Trusted Root CA store - **no effect** because the game uses its bundled OpenSSL CA bundle, not the Windows certificate store
- **Conclusion**: Need a third patch (Patch C) to bypass CA chain verification

### Phase 6: Applying Patch C (CA Chain Verification Bypass)

**Goal**: Bypass OpenSSL's built-in CA certificate chain verification.

- Found `ssl_verify_cert_chain` in the map file at VA `0x0000000141498530`
- Initially tried to find `SSL_CTX_set_verify` inside the `initOpenSSLContext` function to set a custom verify callback, but user couldn't locate it (the call may be indirect or via a different code path)
- **Pivoted to simpler approach**: Patch `ssl_verify_cert_chain` directly at its entry point
- **Patch C**: At function entry, assembled:
  ```asm
  mov eax, 1    ; return 1 (chain verified)
  ret
  ```
- **User confirmed**: "it works!" - Full TLS 1.3 handshake completed, game sent actual HTTPS requests to mock server
- All three patches saved together as `ua_engine_final.exe`

### Phase 7: Capturing Live API Traffic

**Goal**: Understand what API calls the game makes to Ubisoft's servers.

**Traffic captured on mock server**:
```
POST /v3/profiles/sessions
  Authorization: Basic VmVuX0pEMjAxNkB1Ymlzb2Z0LmNvbTojSkQyMDE2dWJpNDI=
  Ubi-AppBuildId: BUILDID_324393
  Ubi-AppId: c8cfd4b7-91b0-446b-8e3b-7edfa393c946
  Body: {}

GET /v1/applications/c8cfd4b7-91b0-446b-8e3b-7edfa393c946/parameters
  ?parameterGroups=us-staging,us-sdkClientUrlsPlaceholders,us-sdkClientClub,
   us-sdkClientFeaturesSwitches,us-sdkClientLogin,us-sdkClientUrls,
   us-sdkClientChina,us-sdkClientUplay

GET /v3/policies/US?languageCode=FR&contentFormat=plain
```

**Findings**:
- Game authenticates with Basic auth (decoded: `Ven_JD2016@ubisoft.com:#JD2016ubi42`)
- Game requests 8 parameter groups from the application config endpoint
- `us-sdkClientUrls` group likely contains the JMCS service URL
- Game also requests US region policies with French language (contentFormat=plain)
- Updated `server.js` to return proper mock responses for each endpoint

**Observation**: The `ubi-sessionid` header does not appear on the parameters/policies GET requests. The game may use a different authentication flow for those, or they may be pre-auth endpoints that don't need the session ticket.

### Phase 8: JMCS Blocker Discovery

**Goal**: Get the Mobile/Phone controller option to work.

- Clicked "Mobile" in the game with mock server running
- **Result**: "Ubisoft server error" popup appeared
- **No new HTTP requests** appeared on the mock server beyond the initial login sequence
- `Task_CreateJMCSSession_Ubiservices::start` was never called

**Root cause analysis**:
- The parameters endpoint returns `{ parameters: [] }` (empty)
- The game needs specific parameters (especially from `us-sdkClientUrls`) to discover the JMCS endpoint URL
- Without the JMCS URL, the game can't even attempt to create a JMCS session
- The `startCreatingJMCSSession` function (VA `0x1408e78a0`) is never reached

**Map file exploration** revealed the full JMCS lifecycle:
1. `startCreatingJMCSSession` triggers `Task_CreateJMCSSession_Ubiservices`
2. The task does an HTTP POST to create the session
3. On success: `onJMCSSessionCreationSuccess` receives `JmcsSessionInfo`
4. `HttpHelper::setJMCSSessionId` stores the session ID globally
5. `JD_GS_UIConnectPhone::setPairingCode` displays the code on screen
6. Phone app connects via WebSocket, handled by `JD_PhoneScoringProtocol`
7. Commands: `PhoneDataCmdHandshakeContinue`, `SyncStart`, `SyncEnd`
8. `JD_SmartphoneDataQueue::insertReceivedScoringData` processes motion data

**This is where progress currently stands. The next step is to find what parameter names the game expects for the JMCS URL.**

### Summary of All Failures and Their Solutions

| # | Failure | Error/Symptom | Root Cause | Solution |
|---|---------|---------------|------------|----------|
| 1 | Game crashes on device selection | `isSessionValid()` assert | No Ubisoft session exists | Patch A: `je` → `jmp` |
| 2 | TLS handshake fails | `no suitable signature algorithm` | RSA cert + TLS 1.3 (no RSA-PSS) | Switch to ECDSA P-256 cert |
| 3 | TLS version mismatch | `no shared cipher` | Forcing TLS 1.2, game only does 1.3 | Let server do TLS 1.3 (remove maxVersion) |
| 4 | Cipher relaxation fails | `ALL:@SECLEVEL=0` broken | Node.js v24 OpenSSL 3.x incompatibility | Not needed after ECDSA fix |
| 5 | Cert rejected after handshake | `tlsv1 alert unknown ca` (48) | Bundled OpenSSL CA store rejects self-signed | Patch C: `ssl_verify_cert_chain` → return 1 |
| 6 | Cert pinning rejects cert | Connection refused | `sslcertificatevalidator.cpp` callback | Patch B: validator → return 1 |
| 7 | Patches in separate files | Only one patch active | Each export overwrites previous patches | Apply all patches to same binary, export once |
| 8 | JMCS session never created | "Ubisoft server error" on Mobile | Empty parameters response, no JMCS URL | **UNSOLVED** - need to find parameter names |

---

## Environment

- **OS**: Windows 10 (19044.6937)
- **Node.js**: v24.11.1
- **Python**: 3.14.0
- **x64dbg**: Used for binary patching
- **Game location**: `d:\jd2021pc\jd21\`
- **Mock server**: `d:\jd2021pc\mock-server\`
