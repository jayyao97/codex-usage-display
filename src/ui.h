#pragma once

#include "app_state.h"

enum class UiAction : uint8_t {
  kFocusCodex,
  kRefresh,
  kNewTask,
  kReconnect,
};

using UiActionHandler = void (*)(UiAction action);

void uiCreate(UiActionHandler action_handler);
void uiUpdate(const AppState& state, uint32_t elapsed_seconds);
void uiShowQuickActions();
void uiShowToast(const char* text);
void uiShowPairingCode(uint32_t passkey);
void uiHidePairingCode();
bool uiPairingCodeVisible();
