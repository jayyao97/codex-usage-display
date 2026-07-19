#include "ble_bridge.h"

#include <ArduinoJson.h>
#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLESecurity.h>

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

namespace {

constexpr char kDeviceName[] = "Codex Display";
constexpr char kServiceUuid[] = "7d8b6c20-8f6d-4b44-a0f8-1b6570c0de01";
constexpr char kStatusUuid[] = "7d8b6c20-8f6d-4b44-a0f8-1b6570c0de02";
constexpr char kCommandUuid[] = "7d8b6c20-8f6d-4b44-a0f8-1b6570c0de03";
constexpr char kResultUuid[] = "7d8b6c20-8f6d-4b44-a0f8-1b6570c0de04";
constexpr char kDeviceInfoUuid[] = "7d8b6c20-8f6d-4b44-a0f8-1b6570c0de05";
constexpr uint8_t kProtocolVersion = 1;

BLEServer* server = nullptr;
BLECharacteristic* command_characteristic = nullptr;
QueueHandle_t state_queue = nullptr;
QueueHandle_t result_queue = nullptr;
QueueHandle_t pairing_code_queue = nullptr;
QueueHandle_t pairing_finished_queue = nullptr;
volatile bool connected = false;
uint32_t next_request_id = 1;
uint32_t command_session_id = 0;
uint32_t last_sequence = 0;

class ServerCallbacks final : public BLEServerCallbacks {
 public:
  void onConnect(BLEServer*) override {
    connected = true;
    last_sequence = 0;
    Serial.println("[ble] connected");
  }

  void onDisconnect(BLEServer* current_server) override {
    connected = false;
    Serial.println("[ble] disconnected");
    current_server->startAdvertising();
  }
};

class StatusCallbacks final : public BLECharacteristicCallbacks {
 public:
  void onWrite(BLECharacteristic* characteristic) override {
    const String value = characteristic->getValue();
    if (value.isEmpty() || value.length() > 256) {
      Serial.println("[ble] rejected invalid status length");
      return;
    }

    JsonDocument document;
    const DeserializationError error =
        deserializeJson(document, value.c_str(), value.length());
    if (error || document["v"].as<uint8_t>() != kProtocolVersion) {
      Serial.println("[ble] rejected invalid status JSON");
      return;
    }

    const uint32_t sequence = document["s"] | 0UL;
    if (sequence == 0 || (last_sequence != 0 && sequence < last_sequence)) {
      Serial.println("[ble] rejected stale status");
      return;
    }

    AppState state;
    state.unix_time = document["t"] | 0ULL;
    state.utc_offset_minutes = document["o"] | 0;
    state.remaining_percent =
        min<uint8_t>(document["r"] | 0, static_cast<uint8_t>(100));
    state.limit_window_minutes = document["u"] | 0UL;
    state.quota_reset_seconds = document["q"] | 0UL;
    state.tokens_today = document["d"] | 0ULL;
    state.tokens_today_estimated = (document["e"] | 0) == 1;
    state.tokens_7d = document["w"] | 0ULL;
    state.reset_credits =
        min<uint8_t>(document["c"] | 0, static_cast<uint8_t>(255));
    state.next_credit_expiry_seconds = document["x"] | 0UL;
    state.active_threads =
        min<uint8_t>(document["a"] | 0, static_cast<uint8_t>(255));
    state.connection = ConnectionState::kLinked;
    state.time_valid = state.unix_time > 0;
    state.data_valid = true;

    last_sequence = sequence;
    xQueueOverwrite(state_queue, &state);
    Serial.printf("[ble] status seq=%lu\n",
                  static_cast<unsigned long>(sequence));
  }
};

class ResultCallbacks final : public BLECharacteristicCallbacks {
 public:
  void onWrite(BLECharacteristic* characteristic) override {
    const String value = characteristic->getValue();
    JsonDocument document;
    if (deserializeJson(document, value.c_str(), value.length()) ||
        document["v"].as<uint8_t>() != kProtocolVersion) {
      return;
    }

    BleActionResult result{};
    result.request_id = document["id"] | 0UL;
    result.ok = (document["ok"] | 0) == 1;
    const char* message = document["m"] | (result.ok ? "DONE" : "FAILED");
    strlcpy(result.message, message, sizeof(result.message));
    xQueueOverwrite(result_queue, &result);
  }
};

class SecurityCallbacks final : public BLESecurityCallbacks {
 public:
  void onPassKeyNotify(uint32_t passkey) override {
    xQueueOverwrite(pairing_code_queue, &passkey);
    Serial.printf("[ble] pairing passkey %06lu\n",
                  static_cast<unsigned long>(passkey));
  }

  bool onSecurityRequest() override {
    return true;
  }

#if defined(CONFIG_BLUEDROID_ENABLED)
  void onAuthenticationComplete(esp_ble_auth_cmpl_t result) override {
    const bool success = result.success;
    xQueueOverwrite(pairing_finished_queue, &success);
    Serial.printf("[ble] pairing %s\n", success ? "complete" : "failed");
  }
#endif
};

}  // namespace

bool bleBegin() {
  state_queue = xQueueCreate(1, sizeof(AppState));
  result_queue = xQueueCreate(1, sizeof(BleActionResult));
  pairing_code_queue = xQueueCreate(1, sizeof(uint32_t));
  pairing_finished_queue = xQueueCreate(1, sizeof(bool));
  if (state_queue == nullptr || result_queue == nullptr ||
      pairing_code_queue == nullptr || pairing_finished_queue == nullptr) {
    Serial.println("[ble] failed to allocate queues");
    return false;
  }

  BLEDevice::init(kDeviceName);
  command_session_id = esp_random();
  if (command_session_id == 0) {
    command_session_id = 1;
  }
  BLEDevice::setMTU(256);
  BLEDevice::setSecurityCallbacks(new SecurityCallbacks());

  auto* security = new BLESecurity();
  security->setAuthenticationMode(true, true, true);
  security->setCapability(ESP_IO_CAP_OUT);
  security->setPassKey(false);
  security->regenPassKeyOnConnect(true);

  server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());
  server->advertiseOnDisconnect(true);

  BLEService* service = server->createService(kServiceUuid);
  BLECharacteristic* status = service->createCharacteristic(
      kStatusUuid, BLECharacteristic::PROPERTY_WRITE);
  status->setAccessPermissions(ESP_GATT_PERM_WRITE_ENCRYPTED);
  status->setCallbacks(new StatusCallbacks());

  command_characteristic = service->createCharacteristic(
      kCommandUuid,
      BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
  command_characteristic->setAccessPermissions(ESP_GATT_PERM_READ_ENCRYPTED);
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"
  auto* command_cccd = new BLE2902();
#pragma GCC diagnostic pop
  command_cccd->setAccessPermissions(ESP_GATT_PERM_READ |
                                     ESP_GATT_PERM_WRITE_ENCRYPTED);
  command_characteristic->addDescriptor(command_cccd);

  BLECharacteristic* result = service->createCharacteristic(
      kResultUuid, BLECharacteristic::PROPERTY_WRITE);
  result->setAccessPermissions(ESP_GATT_PERM_WRITE_ENCRYPTED);
  result->setCallbacks(new ResultCallbacks());

  BLECharacteristic* device_info = service->createCharacteristic(
      kDeviceInfoUuid, BLECharacteristic::PROPERTY_READ);
  device_info->setValue("{\"v\":1,\"fw\":\"0.1.0\",\"screen\":\"480x480\"}");

  service->start();
  BLEAdvertising* advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(kServiceUuid);
  advertising->setScanResponse(true);
  BLEDevice::startAdvertising();
  Serial.println("[ble] advertising as Codex Display");
  return true;
}

bool bleConnected() {
  return connected;
}

void bleStartAdvertising() {
  if (!connected && server != nullptr) {
    server->startAdvertising();
  }
}

bool bleTakeState(AppState& state) {
  return state_queue != nullptr &&
         xQueueReceive(state_queue, &state, 0) == pdTRUE;
}

bool bleTakeActionResult(BleActionResult& result) {
  return result_queue != nullptr &&
         xQueueReceive(result_queue, &result, 0) == pdTRUE;
}

bool bleTakePairingCode(uint32_t& passkey) {
  return pairing_code_queue != nullptr &&
         xQueueReceive(pairing_code_queue, &passkey, 0) == pdTRUE;
}

bool bleTakePairingFinished(bool& success) {
  return pairing_finished_queue != nullptr &&
         xQueueReceive(pairing_finished_queue, &success, 0) == pdTRUE;
}

bool bleSendAction(const char* action) {
  if (!connected || command_characteristic == nullptr) {
    return false;
  }

  char message[96];
  const uint32_t request_id = next_request_id++;
  snprintf(message, sizeof(message),
           "{\"v\":1,\"sid\":%lu,\"id\":%lu,\"a\":\"%s\"}",
           static_cast<unsigned long>(command_session_id),
           static_cast<unsigned long>(request_id), action);
  command_characteristic->setValue(message);
  command_characteristic->notify();
  return true;
}

bool bleClearBonds() {
#if defined(CONFIG_BLUEDROID_ENABLED)
  int count = esp_ble_get_bond_device_num();
  if (count <= 0) {
    return true;
  }

  auto* devices = static_cast<esp_ble_bond_dev_t*>(
      malloc(sizeof(esp_ble_bond_dev_t) * count));
  if (devices == nullptr ||
      esp_ble_get_bond_device_list(&count, devices) != ESP_OK) {
    free(devices);
    return false;
  }

  bool cleared = true;
  for (int i = 0; i < count; ++i) {
    if (esp_ble_remove_bond_device(devices[i].bd_addr) != ESP_OK) {
      cleared = false;
    }
  }
  free(devices);
  return cleared;
#else
  return false;
#endif
}
