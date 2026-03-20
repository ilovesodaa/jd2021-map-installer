# Mobile Scoring Revival - Session 3 Report

## Date: March 10, 2026

## Goal
Continue restoring mobile phone scoring (JMCS) in Just Dance 2021 PC. This session focused on fixing a boot crash caused by overly aggressive patches from session 2's end, then pushing deeper into the JMCS session creation pipeline.

## Starting State (from Session 2)
- **22 patches** existed (A through W), with U, V, W added at the very end of session 2
- **Boot crash**: Patches U + V caused the game to crash during startup
- Patch U (force state 3 in update()'s State 0 handler) fired every frame during boot before session data existed
- Patch V (getSessionStatus -> return 1 globally) affected ALL callers during boot, not just UIConnectPhone
- Patch W (NOP first-run flag clear) was fine

## Summary of Work Done

### Phase 1: Fix Boot Crash (Patches U + V Redesigned)

**Root Cause Analysis:**
- **Old Patch U** patched the `update()` function's State 0 handler at VA `0x1408E4B30` to force `m_state = 3`. This fired every single frame during boot, before any session data structures existed, causing a null pointer crash.
- **Old Patch V** made `getSessionStatus()` at VA `0x1408E4EE0` return 1 (Active) for ALL callers. During boot, many subsystems call `getSessionStatus()` and don't expect an active session this early.

**Solution: Targeted patches that only fire during the Mobile click flow.**

#### New Patch U: Patch `forceRequestRefresh` instead of `update`
- **Function**: `SessionService_Ubiservices::forceRequestRefresh` at VA `0x1408E2950`
- **Key insight**: `forceRequestRefresh` is ONLY called from `DeviceSelection::validate()` when the user clicks "Mobile" on the controller select screen. It is never called during boot.
- **Original behavior**: Checks if `m_state == 4` (error), resets to 0 for retry
- **Patched behavior**: Unconditionally sets `m_state = 3` (active) and `byte [rcx+10Eh] = 1` (JMCS needed flag), then returns
- **Bytes**: `C7 81 08 01 00 00 03 00 00 00 C6 81 0E 01 00 00 01 C3`
- **Why this works**: When the state machine's `updateReady` (State 3 handler) runs on the next tick, it sees the JMCS flag at `+0x10E` and calls `startCreatingJMCSSession`

#### New Patch V: NOP the `jne` in UIConnectPhone_Update::process
- **Location**: VA `0x140716D3A` in `UIConnectPhone_Update::process`
- **Original**: `75 12` (jne +0x12 -- skip setPairingCode if status != 1)
- **Patched**: `90 90` (NOP NOP -- always fall through to setPairingCode)
- **Why this is safe**: This patch only affects the UIConnectPhone screen, not any boot-time code path

**Result**: Game boots successfully. Clicking Mobile now triggers `startCreatingJMCSSession`.

### Phase 2: New Assertion Error - Empty JMCS Server URL

After fixing the boot crash, clicking Mobile produced a new assertion error:

```
File: onlineadapter_ubiservices.cpp(269)
Condition: "!serverUrl.isEmpty()"

ITF::OnlineAdapter_Ubiservices::getNodeJsServiceUrl
ITF::HttpHelper::buildNodeJsServiceUrl
ITF::Task_CreateJMCSSession_Ubiservices::start
```

**This is progress** -- the JMCS session creation path IS reached. But `getNodeJsServiceUrl` reads the server URL from `[adapter+8]+0x30`, which is empty because the Ubiservices entity URL was never populated.

### Phase 3: Investigating the URL Source

Deep analysis of `getNodeJsServiceUrl` (VA `0x1408D91B0`, file offset `0x8D85B0`):

1. **Function signature**: `getNodeJsServiceUrl(this=rcx, sret=rdx, serviceName=r8, version=r9d)`
2. **URL source**: Reads from `[this+8]+0x30` -- the OnlineAdapter's configuration object
3. **Format**: Uses `%s/%s/v%d` (at VA `0x14267EBE8`) to produce URLs like `https://public-ubiservices.ubi.com/jmcs/v1`
4. **Helper functions**: `c_str` at VA `0x14175E330`, `string_format` at VA `0x14172B590`
5. **Two assertions**: Null check (line 265) and empty check (line 269)

**Why the URL is empty:**
- Searched the binary for JSON field names `"entities"`, `"entityId"`, `"url"` -- NOT FOUND
- Searched for `"SmartphoneServiceUrl"`, `"JmcsHost"` -- NOT FOUND in binary
- The mock server's entities endpoint returns `obj.url: 'https://public-ubiservices.ubi.com'` but the SDK doesn't parse these field names because they don't exist in the binary
- The entity search response format from our mock server doesn't match what the Ubiservices SDK expects internally

**Call chain analysis:**
```
Task_CreateJMCSSession_Ubiservices::start (VA 0x14097B990)
  -> buildNodeJsServiceUrl (VA 0x1408CF680)
     -> loads OnlineAdapter singleton from global at VA 0x143196428
     -> getNodeJsServiceUrl (VA 0x1408D91B0)
        -> reads URL from [adapter+8]+0x30  (EMPTY!)
        -> ASSERTS !serverUrl.isEmpty()
```

### Phase 4: Implementing Patch X - Hardcoded URL

**Design decision**: Rather than trying to fix the entity search/parse pipeline (which is deep inside the Ubiservices SDK with no visible JSON field names), embed the URL directly in the binary and rewrite `getNodeJsServiceUrl` to use it.

#### Patch X1: Embed URL String in .data Section
- **Location**: VA `0x1430D6205` (file offset `0x30D4405`)
- **Content**: `https://public-ubiservices.ubi.com\0` (35 bytes)
- **Verification**: Confirmed this is in a large block of unused zeroes in the `.data` section (23,197 bytes of contiguous zeros)

#### Patch X2: Rewrite getNodeJsServiceUrl
- **Location**: VA `0x1408D91CA` (file offset `0x8D85CA`) -- starts after the 26-byte prologue
- **Size**: 82 bytes of new code + 104 bytes CC padding (replaces 186-byte original body)

**New code disassembly:**
```asm
; Save parameters
mov ebp, r9d            ; version
mov r14, r8             ; serviceName pointer
mov rsi, rdx            ; sret pointer

; Get serviceName as C string
mov rcx, r14
call c_str              ; VA 0x14175E330
mov rbx, rax            ; rbx = serviceName c_str

; Load hardcoded URL
lea rax, [rip+0x027FD020]  ; -> VA 0x1430D6205 = "https://public-ubiservices.ubi.com"

; Call string_format("%s/%s/v%d", serverUrl, serviceName, version)
mov r8, rax             ; r8 = serverUrl (1st %s)
mov [rsp+20h], ebp      ; [rsp+20h] = version (%d)
mov r9, rbx             ; r9 = serviceName (2nd %s)
lea rdx, [rip+0x01DA59F2]  ; rdx = "%s/%s/v%d" at VA 0x14267EBE8
mov rcx, rsi            ; rcx = sret output pointer
call string_format      ; VA 0x14172B590

; Epilogue (matches original register restore)
mov rbx, [rsp+40h]
mov rax, rsi            ; return sret pointer
mov rsi, [rsp+50h]
mov rbp, [rsp+48h]
mov rdi, [rsp+58h]
add rsp, 30h
pop r14
ret
```

**RIP-relative displacement verification:**
| Instruction | Source VA (after inst) | Target VA | Displacement | Verified |
|-------------|----------------------|-----------|-------------|----------|
| `call c_str` | `0x1408D91DB` | `0x14175E330` | `0x00E85155` | Correct |
| `lea rax, [URL]` | `0x1408D91E5` | `0x1430D6205` | `0x027FD020` | Correct |
| `lea rdx, [fmt]` | `0x1408D91F6` | `0x14267EBE8` | `0x01DA59F2` | Correct |
| `call string_format` | `0x1408D91FE` | `0x14172B590` | `0x00E52392` | Correct |

**Epilogue verification**: Read original epilogue bytes at file offset `0x8D8670`, confirmed exact match with our epilogue bytes:
```
48 8B 5C 24 40  48 8B C6  48 8B 74 24 50  48 8B 6C 24 48  48 8B 7C 24 58  48 83 C4 30  41 5E  C3
```

## All Patches (22 Active)

### SSL/Session Bypass
| Patch | Function | VA | Effect |
|-------|----------|-----|--------|
| A | isSessionValid assert | Auto-found | je -> jmp (skip assert) |
| B | certVerifyCallback | `0x1416D3CE0` | Return 1 (accept all certs) |
| C | ssl_verify_cert_chain | `0x141498530` | Return 1 (accept all certs) |

### Subscription/S2S Error Suppression
| Patch | Function | VA | Effect |
|-------|----------|-----|--------|
| D | showS2SServerError | `0x14028E730` | Return false |
| E | enableS2SErrorPopupDisplay | `0x1406E34C0` | Ret immediately |
| F | enableS2SErrorDisplayAfterSubscriptionRefresh | `0x1406E3380` | Ret immediately |
| I | RefreshSubscriptionInfoTask::start | `0x14092BE80` | Ret immediately |
| J | refreshUserSubscription | `0x14092BD60` | Ret immediately |

### Error Popup Suppression
| Patch | Function | VA | Effect |
|-------|----------|-----|--------|
| K | displayErrorPopup | `0x14071FC40` | Ret immediately |
| L | buildGameplayMessage | `0x1400E5060` | Return NULL |
| M | buildMessageFromConfig | `0x1400E51F0` | Return NULL |
| O | addOnlineErrorMessage | `0x140BE0690` | Ret immediately |
| P | addGameplayMessage | `0x140BE03F0` | Ret immediately |
| Q | addMessage | `0x140BE0500` | Ret immediately |

### Online Features Boot Fix
| Patch | Function | VA | Effect |
|-------|----------|-----|--------|
| R | IsOnlineTask::onPingFailure | `0x140324EC4` | Write true instead of false |
| S | onAvailabilityFailure | `0x140324B30` | Jump to onAvailabilitySuccess |

### Mobile Phone Pairing Flow
| Patch | Function | VA | Effect |
|-------|----------|-----|--------|
| T | processPendingValidation | `0x14041BC10` | Return 4 (success) |
| U | forceRequestRefresh | `0x1408E2950` | Set state 3 + JMCS flag |
| V | UIConnectPhone status check | `0x140716D3A` | NOP jne (always call setPairingCode) |
| W | setPairingCode retry flag | `0x140716D45` | NOP flag clear (retry every tick) |

### JMCS URL Fix
| Patch | Function | VA | Effect |
|-------|----------|-----|--------|
| X1 | (data) URL string | `0x1430D6205` | Embed `https://public-ubiservices.ubi.com` |
| X2 | getNodeJsServiceUrl | `0x1408D91CA` | Use hardcoded URL via RIP-relative LEA |

### Skipped Patches (Would Crash)
| Patch | Function | Reason |
|-------|----------|--------|
| G | getSessionError | Returns OnlineError by value; xor eax,eax;ret corrupts sret buffer |
| H | getSessionStatus | Unknown correct enum value; complex stack setup |
| N | checkOnlineFeaturesAvailable | Boot sequence depends on async task init from this function |

## Key Architecture Findings (New This Session)

### SessionService_Ubiservices State Machine
```
State 0: Idle/Polling (initial state after boot)
State 1: Creating session (Ubiservices handshake)
State 2: Creating JMCS session
State 3: Active (ready for JMCS)
State 4: Error/Retry/Wait
State 5: Deleting session
State 6: Terminal

Offset +0x108: m_state (dword)
Offset +0x10E: JMCS needed flag (byte)
```

### getSessionStatus() Mapping (VA 0x1408E4EE0)
```
Internal states {0,1,2,5,6} -> ESessionStatus_None (0)
Internal state 3             -> ESessionStatus_Active (1)
Internal state 4             -> ESessionStatus_Error (2)
```

### forceRequestRefresh Flow (Original)
```
forceRequestRefresh (VA 0x1408E2950)
  Called by: DeviceSelection::validate() (only when user clicks Mobile)
  Original: if m_state == 4, reset timer and set m_state = 0
  Patched:  unconditionally set m_state = 3, JMCS flag = 1, return
```

### JMCS Session Creation Pipeline
```
User clicks "Mobile" on controller select screen
  -> DeviceSelection::validate()
     -> forceRequestRefresh()  [PATCHED: sets state 3 + JMCS flag]
     -> processPendingValidation()  [PATCHED: returns 4 = success]
  -> Navigate to UIConnectPhone screen
     -> UIConnectPhone_Update::process
        -> getSessionStatus()  [PATCHED: NOP jne, always proceed]
        -> setPairingCode()    [PATCHED: retry flag kept alive]
  -> Meanwhile, state machine sees state 3 + JMCS flag
     -> updateReady() (state 3 handler)
        -> startCreatingJMCSSession (VA 0x1408E78A0)
           -> checks m_state accepts 1 or 3, sets m_state = 2
           -> Task_CreateJMCSSession_Ubiservices::start (VA 0x14097B990)
              -> buildNodeJsServiceUrl()  [calls getNodeJsServiceUrl]
              -> getNodeJsServiceUrl()    [PATCHED: uses hardcoded URL]
              -> Constructs URL: https://public-ubiservices.ubi.com/{service}/v{version}
              -> HTTP POST to create JMCS session
```

### getNodeJsServiceUrl Internal Structure (VA 0x1408D91B0)
```
Prologue (26 bytes): Save rbx, rbp, rsi, rdi to stack home area; push r14; sub rsp, 30h
Body (186 bytes):
  - Save params: rcx->rbx(this), rdx->rsi(sret), r8->r14(serviceName), r9d->ebp(version)
  - Load config: rax = [rbx+8] (config object)
  - Get URL: rdi = [rax+30h] (server URL string)
  - Assert not null (line 265), assert not empty (line 269)
  - Call c_str on serviceName (VA 0x14175E330)
  - Call c_str on serverUrl (VA 0x140994CD0)
  - Format "%s/%s/v%d" via string_format (VA 0x14172B590)
Epilogue (30 bytes): Restore rbx, rsi, rbp, rdi; add rsp,30h; pop r14; ret
```

### buildNodeJsServiceUrl (VA 0x1408CF680)
```
- Loads OnlineAdapter singleton from global at [rip+0x28C6D7C] (VA 0x143196428)
- Calls getNodeJsServiceUrl with: serviceName, version=1
- Returns formatted URL string
- Has String cleanup with refcount decrement: lock xadd [rcx+8], -1
```

### PE Section Layout
```
.text:  VA 0x1000,     File 0x400,     Size 0x1CD1600
.rdata: VA 0x1CD3000,  File 0x1CD1A00, Size 0x13E6800
.data:  VA 0x30BA000,  File 0x30B8200, Size 0xDC200
```

### ubiservices::String Type
- Refcounted pointer type
- `[ptr+0]` = vtable
- `[ptr+8]` = refcount
- Cleanup uses `lock xadd [rcx+8], -1` for thread-safe atomic decrement

## Current Game Behavior (End of Session)
1. **Boot**: Works (patches R + S bypass online features check)
2. **Main menu**: Reached successfully
3. **Click Mobile**: Navigates to UIConnectPhone screen (patches T + U)
4. **JMCS session creation**: Triggered (patch U sets state 3 + JMCS flag)
5. **URL construction**: Fixed with hardcoded URL (patches X1 + X2)
6. **HTTP POST to JMCS**: Should now attempt to hit mock server -- **UNTESTED**

## What to Expect on Next Test

With Patch X applied, `getNodeJsServiceUrl` will return `https://public-ubiservices.ubi.com/jmcs/v1` (or similar, depending on what `serviceName` and `version` are passed by `Task_CreateJMCSSession_Ubiservices::start`).

The next failure point will likely be one of:
1. **Mock server doesn't handle the JMCS session creation endpoint** -- Need to check what URL path `Task_CreateJMCSSession` constructs and ensure the mock server has a handler for it
2. **Another assertion** in `Task_CreateJMCSSession::start` related to missing fields (auth token, session ID, etc.)
3. **HTTP request failure** if the constructed URL doesn't match a mock server route

### Mock Server JMCS Endpoints (Already Implemented)
The mock server (`server.js`) already has:
- `POST /sessions/v1/session` (lines 619-648): Returns `sessionId` and `pairingCode`

### Expected URL Construction
```
getNodeJsServiceUrl(adapter, sret, "jmcs", 1)
  -> Format: "%s/%s/v%d" = "https://public-ubiservices.ubi.com/jmcs/v1"

buildNodeJsServiceUrl likely appends an endpoint path:
  -> Final URL: "https://public-ubiservices.ubi.com/jmcs/v1/sessions" (or similar)
```

The mock server's existing handler at `/sessions/v1/session` may need to be adjusted to match the actual URL the game constructs.

## Key Files Modified This Session

| File | Changes |
|------|---------|
| `MobileScoringRevivalProject/patcher.py` | Revised Patches U + V (targeted instead of global); Added Patches X1 + X2 (JMCS URL fix) |
| `jd21/engine/ua_engine_patched.exe` | Regenerated with all 22 patches |

## Key Addresses Discovered This Session

| Symbol | VA | File Offset | Purpose |
|--------|-----|-------------|---------|
| `forceRequestRefresh` | `0x1408E2950` | `0x8E1D50` | Session state reset (patched) |
| `getNodeJsServiceUrl` | `0x1408D91B0` | `0x8D85B0` | JMCS URL builder (rewritten) |
| `buildNodeJsServiceUrl` | `0x1408CF680` | `0x8CEA80` | URL builder wrapper |
| `startCreatingJMCSSession` | `0x1408E78A0` | `0x8E6CA0` | JMCS session creation entry |
| `Task_CreateJMCSSession::start` | `0x14097B990` | `0x97AD90` | JMCS task HTTP initiator |
| `OnlineAdapter singleton` | `0x143196428` | - | Global pointer |
| `jmcsSessionId static` | `0x1431B8FB0` | - | Static session ID storage |
| `"jmcs://" string` | `0x141D38880` | - | JMCS protocol prefix |
| `"%s/%s/v%d" format` | `0x14267EBE8` | - | URL format string |
| `c_str (type 1)` | `0x14175E330` | - | String to char* conversion |
| `c_str (type 2)` | `0x140994CD0` | - | Alt string to char* conversion |
| `string_format` | `0x14172B590` | - | Printf-like string formatter |
| URL data embed | `0x1430D6205` | `0x30D4405` | Hardcoded URL string location |

## Ideas for Next Session

### Immediate: Test Patch X and Handle Next Failure
1. Start mock server, launch patched exe, click Mobile
2. Check mock server logs -- does the JMCS session creation HTTP request arrive?
3. If yes -- does the game process the response correctly?
4. If not -- analyze the next assertion or crash

### Next Likely Issues
1. **URL path mismatch**: The game may construct a different path than what the mock server expects. Check `buildNodeJsServiceUrl` to see what endpoint path it appends after the base URL from `getNodeJsServiceUrl`.
2. **Missing auth headers**: `Task_CreateJMCSSession` likely sends an authorization header with the Ubiservices ticket. The mock server needs to accept it.
3. **Response parsing**: The mock server's JMCS session response format needs to match what the game's SDK expects. Check `onJMCSSessionCreationSuccess` for the expected response fields.
4. **WebSocket upgrade**: After JMCS session creation, the game will try to establish a WebSocket connection for the phone controller protocol. The mock server needs to handle WSS upgrade.

### Longer Term
1. **Pairing code display**: Once JMCS session creation succeeds and returns a pairing code, `setPairingCode` should display it on the UIConnectPhone screen
2. **Phone connection**: A companion phone app (or emulator) needs to connect via WebSocket and send the handshake sequence (Hello -> Continue -> Sync -> SyncEnd)
3. **Accelerometer data**: The phone sends `JD_PhoneScoringData` at 50Hz with accelerometer data in G-force units
4. **LAN discovery alternative**: The PC binary may support UDP LAN discovery on port 6000/7000, potentially bypassing the JMCS cloud path entirely

---

*Report generated at end of Session 3. 22 patches active, game boots and reaches UIConnectPhone screen, JMCS URL assertion fixed but HTTP request result untested.*
