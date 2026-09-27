#pragma once

#include <chrono>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

#include <nlohmann/json.hpp>

#include "hfdns/error.hpp"

namespace hfdns::log {

enum class Level : std::uint8_t { Trace, Debug, Info, Warn, Error };

Result<Level> parse_level(std::string_view text);
std::string_view to_string(Level level) noexcept;

// Initializes the process-wide asynchronous JSON logger. `LOG_LEVEL` from the
// environment, when set, overrides `configured`. Returns the effective level.
Result<Level> init(Level configured, std::optional<std::string_view> env_level);

void set_level(Level level);
bool enabled(Level level) noexcept;
void flush();
void shutdown();

// One JSON object per line: {"ts":..,"level":..,"event":..,<fields>...}.
// Callers pass a stable `event` name so logs are queryable without regexes.
// Never call from the per-query path except at Trace level (see ARCHITECTURE §5).
void write(Level level, std::string_view event,
           const nlohmann::json& fields = nlohmann::json::object());

// Pure formatter behind write(); exposed for tests. Field keys that collide with
// the reserved keys ts/level/event are emitted as "field.<key>" instead of
// overwriting them. Invalid UTF-8 is replaced, never thrown on.
std::string format_record(Level level, std::string_view event, const nlohmann::json& fields,
                          std::chrono::system_clock::time_point ts);

// Log lines dropped because the async queue was full (logging never blocks callers).
std::size_t dropped_records() noexcept;

inline void trace(std::string_view e, const nlohmann::json& f = nlohmann::json::object()) {
    write(Level::Trace, e, f);
}
inline void debug(std::string_view e, const nlohmann::json& f = nlohmann::json::object()) {
    write(Level::Debug, e, f);
}
inline void info(std::string_view e, const nlohmann::json& f = nlohmann::json::object()) {
    write(Level::Info, e, f);
}
inline void warn(std::string_view e, const nlohmann::json& f = nlohmann::json::object()) {
    write(Level::Warn, e, f);
}
inline void error(std::string_view e, const nlohmann::json& f = nlohmann::json::object()) {
    write(Level::Error, e, f);
}

}  // namespace hfdns::log
