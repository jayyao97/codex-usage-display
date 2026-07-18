#pragma once

#include <Arduino.h>

#include "app_state.h"

struct BleActionResult {
  uint32_t request_id;
  bool ok;
  char message[49];
};

bool bleBegin();
bool bleConnected();
void bleStartAdvertising();
bool bleTakeState(AppState& state);
bool bleTakeActionResult(BleActionResult& result);
bool bleTakePairingCode(uint32_t& passkey);
bool bleTakePairingFinished(bool& success);
bool bleSendAction(const char* action);
bool bleClearBonds();
