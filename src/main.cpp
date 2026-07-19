#include <Arduino.h>
#include "board_config.h"

#include <Arduino_GFX_Library.h>
#if __has_include(<TouchDrv.hpp>)
#include <TouchDrv.hpp>
#else
#include <TouchDrvCSTXXX.hpp>
#endif
#include <Wire.h>
#include <XPowersLib.h>
#include <lvgl.h>

#include "app_state.h"
#include "ble_bridge.h"
#include "ui.h"

namespace {

constexpr uint32_t kUiRefreshMs = 1000;
constexpr uint32_t kIdleScreenTimeoutMs = 15 * 1000;
constexpr uint32_t kRunningScreenTimeoutMs = 60 * 1000;
constexpr uint32_t kDataStaleMs = 60 * 1000;
constexpr uint32_t kButtonDebounceMs = 35;
constexpr uint32_t kCodexLongPressMs = 1000;
constexpr uint32_t kBootMaxShortPressMs = 800;
constexpr uint32_t kBootClearPairingMs = 3000;
constexpr size_t kDrawBufferRows = 40;

Arduino_DataBus* display_bus = new Arduino_ESP32QSPI(
    board::kLcdChipSelect, board::kLcdClock, board::kLcdSdio0,
    board::kLcdSdio1, board::kLcdSdio2, board::kLcdSdio3);

Arduino_CO5300* display = new Arduino_CO5300(
    display_bus, board::kLcdReset, 0, board::kScreenWidth,
    board::kScreenHeight, 0, 0, 0, 0);

TouchDrvCST92xx touch;
XPowersPMU power;

lv_disp_draw_buf_t draw_buffer;
lv_color_t* draw_buffer_a = nullptr;
lv_color_t* draw_buffer_b = nullptr;

int16_t touch_x[2] = {};
int16_t touch_y[2] = {};
volatile bool touch_pending = false;

AppState app_state;
uint32_t state_received_at_ms = 0;
uint32_t last_ui_refresh_ms = 0;
uint32_t last_activity_ms = 0;
bool screen_on = true;

struct ButtonState {
  int pin;
  bool stable_pressed = false;
  bool raw_pressed = false;
  bool long_press_sent = false;
  uint32_t raw_changed_at = 0;
  uint32_t pressed_at = 0;
};

ButtonState boot_button{board::kBootButton};
ButtonState codex_button{board::kCodexButton};

void setScreenOn(bool on) {
  if (screen_on == on) {
    return;
  }
  screen_on = on;
  display->setBrightness(on ? board::kDisplayBrightness : 0);
}

void IRAM_ATTR onTouchInterrupt() {
  touch_pending = true;
}

bool consumeTouchInterrupt() {
  noInterrupts();
  const bool pending = touch_pending;
  touch_pending = false;
  interrupts();
  return pending;
}

void displayFlush(lv_disp_drv_t* driver, const lv_area_t* area,
                  lv_color_t* pixels) {
  const uint32_t width = area->x2 - area->x1 + 1;
  const uint32_t height = area->y2 - area->y1 + 1;

#if LV_COLOR_16_SWAP
  display->draw16bitBeRGBBitmap(area->x1, area->y1,
                                reinterpret_cast<uint16_t*>(&pixels->full),
                                width, height);
#else
  display->draw16bitRGBBitmap(area->x1, area->y1,
                              reinterpret_cast<uint16_t*>(&pixels->full),
                              width, height);
#endif

  lv_disp_flush_ready(driver);
}

void roundDisplayArea(lv_disp_drv_t*, lv_area_t* area) {
  if (area->x1 % 2 != 0) {
    --area->x1;
  }
  if (area->y1 % 2 != 0) {
    --area->y1;
  }
  if (area->x2 % 2 == 0) {
    ++area->x2;
  }
  if (area->y2 % 2 == 0) {
    ++area->y2;
  }
}

void readTouch(lv_indev_drv_t*, lv_indev_data_t* data) {
  if (!consumeTouchInterrupt()) {
    data->state = LV_INDEV_STATE_REL;
    return;
  }

  const uint8_t points =
      touch.getPoint(touch_x, touch_y, touch.getSupportTouchPoint());
  if (points == 0) {
    data->state = LV_INDEV_STATE_REL;
    return;
  }

  if (!screen_on) {
    setScreenOn(true);
    last_activity_ms = millis();
    data->state = LV_INDEV_STATE_REL;
    return;
  }

  last_activity_ms = millis();
  data->state = LV_INDEV_STATE_PR;
  data->point.x = touch_x[0];
  data->point.y = touch_y[0];
}

void handleUiAction(UiAction action) {
  const char* command = nullptr;
  switch (action) {
    case UiAction::kFocusCodex:
      command = "focus_codex";
      break;
    case UiAction::kRefresh:
      command = "refresh";
      break;
    case UiAction::kNewTask:
      command = "new_task";
      break;
    case UiAction::kReconnect:
      bleStartAdvertising();
      uiShowToast(bleConnected() ? "BLE CONNECTED" : "BLE ADVERTISING");
      return;
  }

  Serial.printf("[action] %s\n", command);
  if (bleSendAction(command)) {
    uiShowToast("REQUEST SENT");
  } else {
    uiShowToast("COMPANION OFFLINE");
  }
}

bool initPower() {
  if (!power.begin(Wire, AXP2101_SLAVE_ADDRESS, board::kI2cSda,
                   board::kI2cScl)) {
    Serial.println("[pmu] AXP2101 not found");
    return false;
  }

  power.setPowerKeyPressOnTime(XPOWERS_POWERON_128MS);
  power.setPowerKeyPressOffTime(XPOWERS_POWEROFF_6S);
  power.enableLongPressShutdown();
  power.setLongPressPowerOFF();
  power.setChargeTargetVoltage(3);
  Serial.println("[pmu] long-press shutdown configured: 6 seconds");
  return true;
}

bool initDisplay() {
  if (!display->begin()) {
    Serial.println("[display] initialization failed");
    return false;
  }
  display_bus->writeC8D8(0x36, 0xA0);
  display->fillScreen(RGB565_BLACK);
  display->setBrightness(board::kDisplayBrightness);
  return true;
}

bool initTouch() {
  touch.setPins(board::kTouchReset, board::kTouchInterrupt);
  if (!touch.begin(Wire, CST92XX_SLAVE_ADDRESS, board::kI2cSda,
                   board::kI2cScl)) {
    Serial.println("[touch] CST9217 not found");
    return false;
  }

  touch.setMaxCoordinates(board::kScreenWidth, board::kScreenHeight);
  touch.setSwapXY(true);
  touch.setMirrorXY(true, false);
  pinMode(board::kTouchInterrupt, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(board::kTouchInterrupt),
                  onTouchInterrupt, FALLING);
  Serial.printf("[touch] model: %s\n", touch.getModelName());
  return true;
}

bool initLvgl() {
  lv_init();

  constexpr size_t pixel_count = board::kScreenWidth * kDrawBufferRows;
  draw_buffer_a = static_cast<lv_color_t*>(
      heap_caps_malloc(pixel_count * sizeof(lv_color_t),
                       MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL));
  draw_buffer_b = static_cast<lv_color_t*>(
      heap_caps_malloc(pixel_count * sizeof(lv_color_t),
                       MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL));

  if (draw_buffer_a == nullptr) {
    Serial.println("[lvgl] failed to allocate draw buffer");
    return false;
  }

  lv_disp_draw_buf_init(&draw_buffer, draw_buffer_a, draw_buffer_b,
                        pixel_count);

  static lv_disp_drv_t display_driver;
  lv_disp_drv_init(&display_driver);
  display_driver.hor_res = board::kScreenWidth;
  display_driver.ver_res = board::kScreenHeight;
  display_driver.flush_cb = displayFlush;
  display_driver.rounder_cb = roundDisplayArea;
  display_driver.draw_buf = &draw_buffer;
  lv_disp_drv_register(&display_driver);

  static lv_indev_drv_t touch_driver;
  lv_indev_drv_init(&touch_driver);
  touch_driver.type = LV_INDEV_TYPE_POINTER;
  touch_driver.read_cb = readTouch;
  lv_indev_drv_register(&touch_driver);

  uiCreate(handleUiAction);
  state_received_at_ms = millis();
  uiUpdate(app_state, 0);
  return true;
}

template <typename ShortPress, typename LongPress>
void updateButton(ButtonState& button, uint32_t long_press_ms,
                  ShortPress short_press, LongPress long_press) {
  const uint32_t now = millis();
  const bool pressed = digitalRead(button.pin) == LOW;

  if (pressed != button.raw_pressed) {
    button.raw_pressed = pressed;
    button.raw_changed_at = now;
  }

  if (now - button.raw_changed_at < kButtonDebounceMs ||
      button.stable_pressed == button.raw_pressed) {
    if (button.stable_pressed && !button.long_press_sent &&
        now - button.pressed_at >= long_press_ms) {
      button.long_press_sent = true;
      long_press();
    }
    return;
  }

  button.stable_pressed = button.raw_pressed;
  if (button.stable_pressed) {
    button.pressed_at = now;
    button.long_press_sent = false;
    return;
  }

  if (!button.long_press_sent) {
    short_press(now - button.pressed_at);
  }
}

void updateButtons() {
  updateButton(
      boot_button, kBootClearPairingMs,
      [](uint32_t held_ms) {
        if (held_ms <= kBootMaxShortPressMs) {
          setScreenOn(!screen_on);
          if (screen_on) {
            last_activity_ms = millis();
          }
        }
      },
      []() {
        setScreenOn(true);
        uiShowToast(bleClearBonds() ? "PAIRING CLEARED" : "CLEAR FAILED");
        lv_timer_handler();
        delay(750);
        ESP.restart();
      });

  updateButton(
      codex_button, kCodexLongPressMs,
      [](uint32_t) {
        last_activity_ms = millis();
        setScreenOn(true);
        handleUiAction(UiAction::kFocusCodex);
      },
      []() {
        last_activity_ms = millis();
        setScreenOn(true);
        uiShowQuickActions();
      });
}

void refreshUi() {
  const uint32_t now = millis();
  if (now - last_ui_refresh_ms < kUiRefreshMs) {
    return;
  }
  last_ui_refresh_ms = now;
  const uint32_t state_age_seconds = (now - state_received_at_ms) / 1000UL;
  uiUpdate(app_state, state_age_seconds);
}

void updateBle() {
  AppState received_state;
  if (bleTakeState(received_state)) {
    const uint8_t previous_active_threads =
        app_state.data_valid ? app_state.active_threads : 0;
    const bool was_running =
        app_state.data_valid && app_state.active_threads > 0;
    const bool is_running = received_state.active_threads > 0;
    app_state = received_state;
    state_received_at_ms = millis();
    if (received_state.active_threads > previous_active_threads) {
      setScreenOn(true);
      last_activity_ms = millis();
    } else if (was_running && !is_running && screen_on) {
      last_activity_ms = millis();
    }
    // A valid encrypted status proves that secure pairing has completed.
    // Some BLE stack versions do not deliver the authentication callback.
    uiHidePairingCode();
  }

  if (!bleConnected()) {
    app_state.connection = ConnectionState::kDisconnected;
  } else if (!app_state.data_valid) {
    app_state.connection = ConnectionState::kSyncing;
  } else if (millis() - state_received_at_ms >= kDataStaleMs) {
    app_state.connection = ConnectionState::kStale;
  } else {
    app_state.connection = ConnectionState::kLinked;
  }

  BleActionResult action_result;
  if (bleTakeActionResult(action_result)) {
    uiShowToast(action_result.message);
  }

  uint32_t passkey = 0;
  if (bleTakePairingCode(passkey)) {
    setScreenOn(true);
    last_activity_ms = millis();
    uiShowPairingCode(passkey);
  }

  bool pairing_success = false;
  if (bleTakePairingFinished(pairing_success)) {
    uiHidePairingCode();
    uiShowToast(pairing_success ? "PAIRED" : "PAIRING FAILED");
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\nCodex Usage Display starting");

  pinMode(board::kBootButton, INPUT_PULLUP);
  pinMode(board::kCodexButton, INPUT_PULLUP);
  Wire.begin(board::kI2cSda, board::kI2cScl);

  const bool power_ok = initPower();
  const bool display_ok = initDisplay();
  const bool touch_ok = initTouch();

  if (!display_ok || !initLvgl()) {
    Serial.println("[fatal] display stack initialization failed");
    while (true) {
      delay(1000);
    }
  }

  if (!power_ok) {
    uiShowToast("PMU OFFLINE");
  } else if (!touch_ok) {
    uiShowToast("TOUCH OFFLINE");
  }

  if (!bleBegin()) {
    uiShowToast("BLE INIT FAILED");
  }

  Serial.println("Codex Usage Display ready");
  last_activity_ms = millis();
}

void loop() {
  updateButtons();
  updateBle();
  refreshUi();
  lv_timer_handler();

  const uint32_t screen_timeout_ms =
      app_state.data_valid && app_state.active_threads > 0
          ? kRunningScreenTimeoutMs
          : kIdleScreenTimeoutMs;
  if (screen_on && millis() - last_activity_ms >= screen_timeout_ms) {
    setScreenOn(false);
  }

  delay(5);
}
