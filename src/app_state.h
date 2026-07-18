#pragma once

#include <Arduino.h>
#include <stdint.h>

enum class ConnectionState : uint8_t {
  kDisconnected,
  kConnecting,
  kSyncing,
  kLinked,
  kStale,
};

struct AppState {
  uint8_t remaining_percent = 0;
  uint64_t tokens_today = 0;
  uint64_t tokens_7d = 0;
  uint8_t active_threads = 0;

  uint8_t reset_credits = 0;
  uint32_t quota_reset_seconds = 0;
  uint32_t next_credit_expiry_seconds = 0;
  uint32_t limit_window_minutes = 0;

  uint64_t unix_time = 0;
  int16_t utc_offset_minutes = 0;
  ConnectionState connection = ConnectionState::kDisconnected;
  bool time_valid = false;
  bool data_valid = false;
};

String formatCompactTokens(uint64_t tokens);
String formatCountdown(uint32_t seconds);
String formatDateTime(const AppState& state, uint32_t elapsed_seconds = 0);
const char* connectionLabel(ConnectionState state);
