#include "ui.h"

#include <lvgl.h>

#include <algorithm>

LV_FONT_DECLARE(font_montserrat_100);

namespace {

lv_color_t color(uint32_t hex) {
  return lv_color_hex(hex);
}

constexpr uint32_t kCyan = 0x08C9F4;
constexpr uint32_t kWhite = 0xFFFFFF;
constexpr uint32_t kTextMuted = 0x7C878C;
constexpr uint32_t kTextSecondary = 0xAEB8BD;
constexpr uint32_t kTrack = 0x24282B;
constexpr uint32_t kDivider = 0x303538;
constexpr uint32_t kAmber = 0xFFB800;
constexpr uint32_t kOffline = 0xFF5C5C;
constexpr uint32_t kLinked = 0x4DA3FF;
constexpr int kResetSegmentWidth = 22;
constexpr int kResetSegmentGap = 8;
constexpr int kResetTitleGap = 10;
constexpr int kResetOpticalOffset = -8;

UiActionHandler action_handler = nullptr;

lv_obj_t* quota_arc = nullptr;
lv_obj_t* time_label = nullptr;
lv_obj_t* connection_label = nullptr;
lv_obj_t* battery_label = nullptr;
lv_obj_t* quota_title_label = nullptr;
lv_obj_t* quota_value_label = nullptr;
lv_obj_t* percent_label = nullptr;
lv_obj_t* quota_reset_label = nullptr;
lv_obj_t* reset_title_label = nullptr;
lv_obj_t* reset_segments[6] = {};
lv_obj_t* today_value_label = nullptr;
lv_obj_t* week_value_label = nullptr;
lv_obj_t* run_value_label = nullptr;
lv_obj_t* expiry_value_label = nullptr;
lv_obj_t* quick_actions_overlay = nullptr;
lv_obj_t* pairing_overlay = nullptr;
lv_obj_t* pairing_code_label = nullptr;
lv_obj_t* toast = nullptr;
lv_timer_t* toast_timer = nullptr;

void styleLabel(lv_obj_t* label, const lv_font_t* font, uint32_t text_color) {
  lv_obj_set_style_text_font(label, font, LV_PART_MAIN);
  lv_obj_set_style_text_color(label, color(text_color), LV_PART_MAIN);
  lv_obj_set_style_text_opa(label, LV_OPA_COVER, LV_PART_MAIN);
}

lv_obj_t* createLabel(const char* text, const lv_font_t* font,
                      uint32_t text_color, lv_align_t align, int x, int y) {
  lv_obj_t* label = lv_label_create(lv_scr_act());
  lv_label_set_text(label, text);
  styleLabel(label, font, text_color);
  lv_obj_align(label, align, x, y);
  return label;
}

void dispatchAction(lv_event_t* event) {
  if (action_handler == nullptr) {
    return;
  }
  const auto raw = reinterpret_cast<uintptr_t>(lv_event_get_user_data(event));
  action_handler(static_cast<UiAction>(raw));
}

void closeOverlay(lv_event_t*) {
  lv_obj_add_flag(quick_actions_overlay, LV_OBJ_FLAG_HIDDEN);
}

void closePairingOverlay(lv_event_t*) {
  uiHidePairingCode();
}

void dispatchOverlayAction(lv_event_t* event) {
  lv_obj_add_flag(quick_actions_overlay, LV_OBJ_FLAG_HIDDEN);
  dispatchAction(event);
}

void createActionButton(lv_obj_t* parent, const char* text, int y,
                        UiAction action) {
  lv_obj_t* button = lv_btn_create(parent);
  lv_obj_set_pos(button, 50, y);
  lv_obj_set_size(button, 350, 58);
  lv_obj_set_style_radius(button, 10, LV_PART_MAIN);
  lv_obj_set_style_bg_color(button, color(0x091216), LV_PART_MAIN);
  lv_obj_set_style_bg_opa(button, LV_OPA_COVER, LV_PART_MAIN);
  lv_obj_set_style_border_color(button, color(kCyan), LV_PART_MAIN);
  lv_obj_set_style_border_width(button, 1, LV_PART_MAIN);
  lv_obj_set_style_shadow_width(button, 0, LV_PART_MAIN);
  lv_obj_add_event_cb(button, dispatchOverlayAction, LV_EVENT_CLICKED,
                      reinterpret_cast<void*>(static_cast<uintptr_t>(action)));

  lv_obj_t* label = lv_label_create(button);
  lv_label_set_text(label, text);
  styleLabel(label, &lv_font_montserrat_18, kWhite);
  lv_obj_center(label);
}

void hideToast(lv_timer_t*) {
  lv_obj_add_flag(toast, LV_OBJ_FLAG_HIDDEN);
  toast_timer = nullptr;
}

void layoutResetRow(uint8_t segment_count) {
  lv_obj_update_layout(reset_title_label);
  const int title_width = lv_obj_get_width(reset_title_label);
  const int segments_width =
      segment_count == 0
          ? 0
          : segment_count * kResetSegmentWidth +
                (segment_count - 1) * kResetSegmentGap;
  const int group_width =
      title_width +
      (segment_count == 0 ? 0 : kResetTitleGap + segments_width);
  const int start_x =
      (lv_obj_get_width(lv_scr_act()) - group_width) / 2 +
      (segment_count == 0 ? 0 : kResetOpticalOffset);

  lv_obj_set_pos(reset_title_label, start_x, 359);
  const int segments_x = start_x + title_width + kResetTitleGap;
  for (size_t i = 0; i < 6; ++i) {
    lv_obj_set_pos(reset_segments[i],
                   segments_x +
                       static_cast<int>(i) *
                           (kResetSegmentWidth + kResetSegmentGap),
                   362);
  }
}

void createMetricColumn(lv_obj_t* parent, int x, int width, const char* title,
                        lv_obj_t** value_label, bool clickable,
                        UiAction action = UiAction::kFocusCodex) {
  lv_obj_t* column = lv_obj_create(parent);
  lv_obj_remove_style_all(column);
  lv_obj_set_pos(column, x, 0);
  lv_obj_set_size(column, width, 80);
  lv_obj_clear_flag(column, LV_OBJ_FLAG_SCROLLABLE);

  if (clickable) {
    lv_obj_add_flag(column, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(
        column, dispatchAction, LV_EVENT_CLICKED,
        reinterpret_cast<void*>(static_cast<uintptr_t>(action)));
  }

  lv_obj_t* title_label = lv_label_create(column);
  lv_label_set_text(title_label, title);
  styleLabel(title_label, &lv_font_montserrat_12, kCyan);
  lv_obj_set_pos(title_label, 14, 12);

  *value_label = lv_label_create(column);
  lv_label_set_text(*value_label, "--");
  styleLabel(*value_label, &lv_font_montserrat_26, kWhite);
  lv_obj_set_pos(*value_label, 14, 38);
}

}  // namespace

void uiCreate(UiActionHandler handler) {
  action_handler = handler;

  lv_obj_t* screen = lv_scr_act();
  lv_obj_set_style_bg_color(screen, color(0x000000), LV_PART_MAIN);
  lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, LV_PART_MAIN);
  lv_obj_clear_flag(screen, LV_OBJ_FLAG_SCROLLABLE);

  time_label = createLabel("--/-- --:--", &lv_font_montserrat_18,
                           kTextSecondary, LV_ALIGN_TOP_LEFT, 28, 20);

  connection_label = createLabel(LV_SYMBOL_BLUETOOTH " LINKED",
                                 &lv_font_montserrat_14, kTextSecondary,
                                 LV_ALIGN_TOP_RIGHT, -28, 21);
  lv_obj_add_flag(connection_label, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_set_ext_click_area(connection_label, 12);
  lv_obj_add_event_cb(
      connection_label, dispatchAction, LV_EVENT_CLICKED,
      reinterpret_cast<void*>(
          static_cast<uintptr_t>(UiAction::kReconnect)));

  battery_label = createLabel("BAT --%", &lv_font_montserrat_14,
                              kTextSecondary, LV_ALIGN_TOP_RIGHT, -142, 21);
  lv_obj_add_flag(battery_label, LV_OBJ_FLAG_HIDDEN);

  quota_arc = lv_arc_create(screen);
  lv_obj_set_size(quota_arc, 304, 304);
  lv_obj_align(quota_arc, LV_ALIGN_TOP_MID, 0, 54);
  lv_arc_set_rotation(quota_arc, 135);
  lv_arc_set_bg_angles(quota_arc, 0, 270);
  lv_arc_set_range(quota_arc, 0, 100);
  lv_arc_set_value(quota_arc, 68);
  lv_obj_remove_style(quota_arc, nullptr, LV_PART_KNOB);
  lv_obj_set_style_arc_width(quota_arc, 18, LV_PART_MAIN);
  lv_obj_set_style_arc_color(quota_arc, color(kTrack), LV_PART_MAIN);
  lv_obj_set_style_arc_width(quota_arc, 18, LV_PART_INDICATOR);
  lv_obj_set_style_arc_color(quota_arc, color(kCyan), LV_PART_INDICATOR);
  lv_obj_set_style_bg_opa(quota_arc, LV_OPA_TRANSP, LV_PART_MAIN);
  lv_obj_clear_flag(quota_arc, LV_OBJ_FLAG_CLICKABLE);

  quota_title_label = createLabel("7 DAY LEFT", &lv_font_montserrat_18, kCyan,
                                  LV_ALIGN_TOP_MID, 0, 126);

  quota_value_label = createLabel("68", &font_montserrat_100, kWhite,
                                  LV_ALIGN_TOP_MID, -20, 165);
  percent_label = lv_label_create(screen);
  lv_label_set_text(percent_label, "%");
  styleLabel(percent_label, &lv_font_montserrat_26, kWhite);
  lv_obj_align_to(percent_label, quota_value_label, LV_ALIGN_OUT_RIGHT_MID, 2,
                  12);

  quota_reset_label =
      createLabel("QUOTA RESET 2d 8h", &lv_font_montserrat_14, kCyan,
                  LV_ALIGN_TOP_MID, 0, 334);

  reset_title_label = createLabel("RESET", &lv_font_montserrat_12, kTextMuted,
                                  LV_ALIGN_TOP_LEFT, 0, 359);
  for (size_t i = 0; i < 6; ++i) {
    reset_segments[i] = lv_obj_create(screen);
    lv_obj_remove_style_all(reset_segments[i]);
    lv_obj_set_size(reset_segments[i], kResetSegmentWidth, 6);
    lv_obj_set_pos(reset_segments[i], 0, 362);
    lv_obj_set_style_radius(reset_segments[i], LV_RADIUS_CIRCLE, LV_PART_MAIN);
    lv_obj_set_style_bg_color(reset_segments[i], color(kCyan), LV_PART_MAIN);
    lv_obj_set_style_bg_opa(reset_segments[i], LV_OPA_COVER, LV_PART_MAIN);
  }
  layoutResetRow(0);

  lv_obj_t* metrics = lv_obj_create(screen);
  lv_obj_set_pos(metrics, 24, 382);
  lv_obj_set_size(metrics, 432, 74);
  lv_obj_set_style_radius(metrics, 10, LV_PART_MAIN);
  lv_obj_set_style_bg_color(metrics, color(0x020506), LV_PART_MAIN);
  lv_obj_set_style_bg_opa(metrics, LV_OPA_COVER, LV_PART_MAIN);
  lv_obj_set_style_border_color(metrics, color(kCyan), LV_PART_MAIN);
  lv_obj_set_style_border_width(metrics, 1, LV_PART_MAIN);
  lv_obj_set_style_pad_all(metrics, 0, LV_PART_MAIN);
  lv_obj_clear_flag(metrics, LV_OBJ_FLAG_SCROLLABLE);

  createMetricColumn(metrics, 0, 120, "TODAY", &today_value_label, false);
  createMetricColumn(metrics, 120, 108, "LAST 7D", &week_value_label, false);
  createMetricColumn(metrics, 228, 64, "RUN", &run_value_label, true);
  createMetricColumn(metrics, 292, 140, "NEXT EXP", &expiry_value_label, false);

  for (int x : {120, 228, 292}) {
    lv_obj_t* divider = lv_obj_create(metrics);
    lv_obj_remove_style_all(divider);
    lv_obj_set_pos(divider, x, 13);
    lv_obj_set_size(divider, 1, 54);
    lv_obj_set_style_bg_color(divider, color(kDivider), LV_PART_MAIN);
    lv_obj_set_style_bg_opa(divider, LV_OPA_COVER, LV_PART_MAIN);
  }

  quick_actions_overlay = lv_obj_create(screen);
  lv_obj_set_size(quick_actions_overlay, 480, 480);
  lv_obj_set_pos(quick_actions_overlay, 0, 0);
  lv_obj_set_style_bg_color(quick_actions_overlay, color(0x000000), LV_PART_MAIN);
  lv_obj_set_style_bg_opa(quick_actions_overlay, LV_OPA_90, LV_PART_MAIN);
  lv_obj_set_style_border_width(quick_actions_overlay, 0, LV_PART_MAIN);
  lv_obj_set_style_pad_all(quick_actions_overlay, 0, LV_PART_MAIN);
  lv_obj_clear_flag(quick_actions_overlay, LV_OBJ_FLAG_SCROLLABLE);

  lv_obj_t* overlay_title = lv_label_create(quick_actions_overlay);
  lv_label_set_text(overlay_title, "QUICK ACTIONS");
  styleLabel(overlay_title, &lv_font_montserrat_18, kTextSecondary);
  lv_obj_align(overlay_title, LV_ALIGN_TOP_MID, 0, 55);

  createActionButton(quick_actions_overlay, "FOCUS CODEX", 105,
                     UiAction::kFocusCodex);
  createActionButton(quick_actions_overlay, "REFRESH", 178,
                     UiAction::kRefresh);
  createActionButton(quick_actions_overlay, "NEW TASK", 251,
                     UiAction::kNewTask);

  lv_obj_t* cancel = lv_btn_create(quick_actions_overlay);
  lv_obj_set_pos(cancel, 50, 324);
  lv_obj_set_size(cancel, 350, 58);
  lv_obj_set_style_radius(cancel, 10, LV_PART_MAIN);
  lv_obj_set_style_bg_opa(cancel, LV_OPA_TRANSP, LV_PART_MAIN);
  lv_obj_set_style_border_color(cancel, color(kDivider), LV_PART_MAIN);
  lv_obj_set_style_border_width(cancel, 1, LV_PART_MAIN);
  lv_obj_set_style_shadow_width(cancel, 0, LV_PART_MAIN);
  lv_obj_add_event_cb(cancel, closeOverlay, LV_EVENT_CLICKED, nullptr);
  lv_obj_t* cancel_label = lv_label_create(cancel);
  lv_label_set_text(cancel_label, "CANCEL");
  styleLabel(cancel_label, &lv_font_montserrat_18, kTextSecondary);
  lv_obj_center(cancel_label);
  lv_obj_add_flag(quick_actions_overlay, LV_OBJ_FLAG_HIDDEN);

  pairing_overlay = lv_obj_create(screen);
  lv_obj_set_size(pairing_overlay, 420, 250);
  lv_obj_align(pairing_overlay, LV_ALIGN_CENTER, 0, 0);
  lv_obj_set_style_radius(pairing_overlay, 18, LV_PART_MAIN);
  lv_obj_set_style_bg_color(pairing_overlay, color(0x061014), LV_PART_MAIN);
  lv_obj_set_style_bg_opa(pairing_overlay, LV_OPA_COVER, LV_PART_MAIN);
  lv_obj_set_style_border_color(pairing_overlay, color(kCyan), LV_PART_MAIN);
  lv_obj_set_style_border_width(pairing_overlay, 1, LV_PART_MAIN);
  lv_obj_clear_flag(pairing_overlay, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_add_flag(pairing_overlay, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(pairing_overlay, closePairingOverlay, LV_EVENT_CLICKED,
                      nullptr);

  lv_obj_t* pairing_title = lv_label_create(pairing_overlay);
  lv_label_set_text(pairing_title, "ENTER ON YOUR MAC");
  styleLabel(pairing_title, &lv_font_montserrat_18, kTextSecondary);
  lv_obj_align(pairing_title, LV_ALIGN_TOP_MID, 0, 34);

  pairing_code_label = lv_label_create(pairing_overlay);
  lv_label_set_text(pairing_code_label, "000 000");
  styleLabel(pairing_code_label, &lv_font_montserrat_48, kWhite);
  lv_obj_align(pairing_code_label, LV_ALIGN_CENTER, 0, 10);

  lv_obj_t* pairing_hint = lv_label_create(pairing_overlay);
  lv_label_set_text(pairing_hint, "TAP TO DISMISS");
  styleLabel(pairing_hint, &lv_font_montserrat_14, kTextMuted);
  lv_obj_align(pairing_hint, LV_ALIGN_BOTTOM_MID, 0, -30);
  lv_obj_add_flag(pairing_overlay, LV_OBJ_FLAG_HIDDEN);

  toast = lv_label_create(screen);
  lv_label_set_text(toast, "");
  styleLabel(toast, &lv_font_montserrat_14, kWhite);
  lv_obj_set_style_bg_color(toast, color(0x182024), LV_PART_MAIN);
  lv_obj_set_style_bg_opa(toast, LV_OPA_COVER, LV_PART_MAIN);
  lv_obj_set_style_radius(toast, 8, LV_PART_MAIN);
  lv_obj_set_style_pad_hor(toast, 18, LV_PART_MAIN);
  lv_obj_set_style_pad_ver(toast, 12, LV_PART_MAIN);
  lv_obj_align(toast, LV_ALIGN_BOTTOM_MID, 0, -96);
  lv_obj_add_flag(toast, LV_OBJ_FLAG_HIDDEN);
}

void uiUpdate(const AppState& state, uint32_t elapsed_seconds) {
  lv_label_set_text(time_label, formatDateTime(state, elapsed_seconds).c_str());

  const bool linked = state.connection == ConnectionState::kLinked;
  const bool stale = state.connection == ConnectionState::kStale;
  const bool disconnected =
      state.connection == ConnectionState::kDisconnected;
  const String connection =
      String(LV_SYMBOL_BLUETOOTH) + " " + connectionLabel(state.connection);
  lv_label_set_text(connection_label, connection.c_str());
  const uint32_t connection_color =
      linked ? kLinked
             : (disconnected ? kOffline : (stale ? kAmber : kTextMuted));
  lv_obj_set_style_text_color(
      connection_label, color(connection_color),
      LV_PART_MAIN);
  lv_obj_set_style_bg_color(connection_label, color(connection_color),
                            LV_PART_MAIN);
  lv_obj_set_style_bg_opa(
      connection_label,
      disconnected ? LV_OPA_30
                   : ((linked || stale) ? LV_OPA_20 : LV_OPA_TRANSP),
      LV_PART_MAIN);
  lv_obj_set_style_radius(connection_label, 8, LV_PART_MAIN);
  lv_obj_set_style_pad_hor(connection_label, 8, LV_PART_MAIN);
  lv_obj_set_style_pad_ver(connection_label, 4, LV_PART_MAIN);
  lv_obj_align(connection_label, LV_ALIGN_TOP_RIGHT, -24, 16);

  const uint32_t data_accent =
      linked ? kCyan : (stale ? kAmber : kTextMuted);
  lv_obj_set_style_arc_color(quota_arc, color(data_accent),
                             LV_PART_INDICATOR);
  lv_obj_set_style_text_color(quota_title_label, color(data_accent),
                              LV_PART_MAIN);
  lv_obj_set_style_text_color(quota_reset_label, color(data_accent),
                              LV_PART_MAIN);

  if (!state.data_valid) {
    lv_arc_set_value(quota_arc, 0);
    lv_label_set_text(quota_title_label, "CODEX LEFT");
    lv_label_set_text(quota_value_label, "");
    lv_obj_align(quota_value_label, LV_ALIGN_TOP_MID, -20, 165);
    lv_obj_add_flag(percent_label, LV_OBJ_FLAG_HIDDEN);
    lv_label_set_text(quota_reset_label, "WAITING FOR DATA");
    lv_label_set_text(today_value_label, "-");
    lv_label_set_text(week_value_label, "-");
    lv_label_set_text(run_value_label, "-");
    lv_label_set_text(expiry_value_label, "-");
    for (lv_obj_t* segment : reset_segments) {
      lv_obj_add_flag(segment, LV_OBJ_FLAG_HIDDEN);
    }
    return;
  }

  lv_obj_clear_flag(percent_label, LV_OBJ_FLAG_HIDDEN);
  if (state.limit_window_minutes > 0 &&
      state.limit_window_minutes % 1440UL == 0) {
    lv_label_set_text_fmt(quota_title_label, "%lu DAY LEFT",
                          static_cast<unsigned long>(
                              state.limit_window_minutes / 1440UL));
  } else {
    lv_label_set_text(quota_title_label, "CODEX LEFT");
  }

  lv_arc_set_value(quota_arc, std::min<uint8_t>(state.remaining_percent, 100));
  lv_label_set_text_fmt(quota_value_label, "%u", state.remaining_percent);
  lv_obj_align(quota_value_label, LV_ALIGN_TOP_MID, -20, 165);
  lv_obj_align_to(percent_label, quota_value_label, LV_ALIGN_OUT_RIGHT_MID, 2,
                  12);

  const uint32_t quota_seconds =
      state.quota_reset_seconds > elapsed_seconds
          ? state.quota_reset_seconds - elapsed_seconds
          : 0;
  const uint32_t expiry_seconds =
      state.next_credit_expiry_seconds > elapsed_seconds
          ? state.next_credit_expiry_seconds - elapsed_seconds
          : 0;
  const String quota_reset =
      "QUOTA RESET " + formatCountdown(quota_seconds);
  lv_label_set_text(quota_reset_label, quota_reset.c_str());

  String today_tokens = formatCompactTokens(state.tokens_today);
  if (state.tokens_today_estimated) {
    today_tokens = "~" + today_tokens;
  }
  lv_label_set_text(today_value_label, today_tokens.c_str());
  lv_label_set_text(week_value_label,
                    formatCompactTokens(state.tokens_7d).c_str());
  lv_label_set_text_fmt(run_value_label, "%u", state.active_threads);

  const bool has_credits = state.reset_credits > 0;
  const bool expiring_soon =
      has_credits && expiry_seconds <= 48UL * 3600UL;
  const uint32_t reset_color =
      stale || !linked ? kTextMuted : (expiring_soon ? kAmber : kCyan);

  if (state.reset_credits <= 6) {
    lv_label_set_text(reset_title_label, "RESET");
    layoutResetRow(state.reset_credits);
    for (size_t i = 0; i < 6; ++i) {
      if (i < state.reset_credits) {
        lv_obj_clear_flag(reset_segments[i], LV_OBJ_FLAG_HIDDEN);
        const uint32_t segment_color =
            expiring_soon && i == 0 ? kAmber : reset_color;
        lv_obj_set_style_bg_color(reset_segments[i], color(segment_color),
                                  LV_PART_MAIN);
      } else {
        lv_obj_add_flag(reset_segments[i], LV_OBJ_FLAG_HIDDEN);
      }
    }
  } else {
    lv_label_set_text_fmt(reset_title_label, "RESET x%u", state.reset_credits);
    layoutResetRow(0);
    for (lv_obj_t* segment : reset_segments) {
      lv_obj_add_flag(segment, LV_OBJ_FLAG_HIDDEN);
    }
  }

  if (has_credits) {
    lv_label_set_text(expiry_value_label,
                      formatCountdown(expiry_seconds).c_str());
  } else {
    lv_label_set_text(expiry_value_label, "-");
  }
  lv_obj_set_style_text_color(expiry_value_label,
                              color(expiring_soon ? kAmber : kWhite),
                              LV_PART_MAIN);
}

void uiUpdateBattery(int percent, bool charging) {
  if (percent < 0 || percent > 100) {
    lv_obj_add_flag(battery_label, LV_OBJ_FLAG_HIDDEN);
    return;
  }

  lv_label_set_text_fmt(battery_label, charging ? "CHG %d%%" : "BAT %d%%",
                        percent);
  lv_obj_set_style_text_color(
      battery_label, color(charging ? kCyan : kTextSecondary), LV_PART_MAIN);
  lv_obj_clear_flag(battery_label, LV_OBJ_FLAG_HIDDEN);
  lv_obj_align_to(battery_label, connection_label, LV_ALIGN_OUT_LEFT_MID, -12,
                  0);
}

void uiShowQuickActions() {
  lv_obj_clear_flag(quick_actions_overlay, LV_OBJ_FLAG_HIDDEN);
  lv_obj_move_foreground(quick_actions_overlay);
}

void uiShowToast(const char* text) {
  lv_label_set_text(toast, text);
  lv_obj_clear_flag(toast, LV_OBJ_FLAG_HIDDEN);
  lv_obj_align(toast, LV_ALIGN_BOTTOM_MID, 0, -96);
  lv_obj_move_foreground(toast);

  if (toast_timer != nullptr) {
    lv_timer_del(toast_timer);
  }
  toast_timer = lv_timer_create(hideToast, 2000, nullptr);
  lv_timer_set_repeat_count(toast_timer, 1);
}

void uiShowPairingCode(uint32_t passkey) {
  lv_label_set_text_fmt(pairing_code_label, "%03lu %03lu",
                        static_cast<unsigned long>(passkey / 1000UL),
                        static_cast<unsigned long>(passkey % 1000UL));
  lv_obj_clear_flag(pairing_overlay, LV_OBJ_FLAG_HIDDEN);
  lv_obj_move_foreground(pairing_overlay);
}

void uiHidePairingCode() {
  lv_obj_add_flag(pairing_overlay, LV_OBJ_FLAG_HIDDEN);
}

bool uiPairingCodeVisible() {
  return !lv_obj_has_flag(pairing_overlay, LV_OBJ_FLAG_HIDDEN);
}
