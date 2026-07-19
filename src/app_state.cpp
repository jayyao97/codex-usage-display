#include "app_state.h"

#include <time.h>

String formatCompactTokens(uint64_t tokens) {
  if (tokens >= 1000000000000ULL) {
    const double trillions = static_cast<double>(tokens) / 1000000000000.0;
    const uint8_t decimals =
        trillions >= 100 ? 0 : (trillions >= 10 ? 1 : 2);
    return String(trillions, static_cast<unsigned int>(decimals)) + "T";
  }
  if (tokens >= 1000000000ULL) {
    const double billions = static_cast<double>(tokens) / 1000000000.0;
    const uint8_t decimals = billions >= 100 ? 0 : (billions >= 10 ? 1 : 2);
    return String(billions, static_cast<unsigned int>(decimals)) + "B";
  }
  if (tokens >= 1000000ULL) {
    const double millions = static_cast<double>(tokens) / 1000000.0;
    const uint8_t decimals = millions >= 100 ? 0 : (millions >= 10 ? 1 : 2);
    return String(millions, static_cast<unsigned int>(decimals)) + "M";
  }
  if (tokens >= 1000ULL) {
    return String(static_cast<double>(tokens) / 1000.0, 1) + "K";
  }
  return String(static_cast<unsigned long>(tokens));
}

String formatCountdown(uint32_t seconds) {
  const uint32_t days = seconds / 86400UL;
  const uint32_t hours = (seconds % 86400UL) / 3600UL;
  const uint32_t minutes = (seconds % 3600UL) / 60UL;

  if (days > 0) {
    return String(days) + "d " + String(hours) + "h";
  }
  if (hours > 0) {
    return String(hours) + "h " + String(minutes) + "m";
  }
  return String(minutes) + "m";
}

String formatDateTime(const AppState& state, uint32_t elapsed_seconds) {
  if (!state.time_valid) {
    return "--/-- --:--";
  }

  const time_t local_time = static_cast<time_t>(
      state.unix_time + elapsed_seconds +
      static_cast<int64_t>(state.utc_offset_minutes) * 60LL);
  struct tm value {};
  gmtime_r(&local_time, &value);

  char output[16];
  strftime(output, sizeof(output), "%m/%d %H:%M", &value);
  return String(output);
}

const char* connectionLabel(ConnectionState state) {
  switch (state) {
    case ConnectionState::kDisconnected:
      return "OFFLINE";
    case ConnectionState::kConnecting:
      return "SEARCHING";
    case ConnectionState::kSyncing:
      return "SYNCING";
    case ConnectionState::kLinked:
      return "LINKED";
    case ConnectionState::kStale:
      return "STALE";
  }
  return "OFFLINE";
}
