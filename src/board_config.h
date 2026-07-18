#pragma once

#define XPOWERS_CHIP_AXP2101

namespace board {

constexpr int kScreenWidth = 480;
constexpr int kScreenHeight = 480;

constexpr int kLcdSdio0 = 4;
constexpr int kLcdSdio1 = 5;
constexpr int kLcdSdio2 = 6;
constexpr int kLcdSdio3 = 7;
constexpr int kLcdClock = 38;
constexpr int kLcdReset = 39;
constexpr int kLcdChipSelect = 12;

constexpr int kI2cSda = 15;
constexpr int kI2cScl = 14;
constexpr int kTouchInterrupt = 11;
constexpr int kTouchReset = 40;

constexpr int kBootButton = 0;
constexpr int kCodexButton = 18;

constexpr uint8_t kDisplayBrightness = 170;

}  // namespace board
