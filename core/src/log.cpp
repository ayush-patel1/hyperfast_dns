#include "hfdns/log.hpp"

#include <atomic>
#include <format>
#include <memory>

#include <spdlog/async.h>
#include <spdlog/sinks/stdout_sinks.h>
#include <spdlog/spdlog.h>

namespace hfdns::log {

namespace {

constexpr std::size_t kQueueSize = 16384;
constexpr const char* kLoggerName = "hfdns";

std::atomic<int> g_level{static_cast<int>(Level::Info)};
std::shared_ptr<spdlog::logger> g_logger;  // written only by init()/shutdown()

spdlog::level::level_enum to_spdlog(Level level) noexcept {
    switch (level) {
        case Level::Trace:
            return spdlog::level::trace;
        case Level::Debug:
            return spdlog::level::debug;
        case Level::Info:
            return spdlog::level::info;
        case Level::Warn:
            return spdlog::level::warn;
        case Level::Error:
            return spdlog::level::err;
    }
    return spdlog::level::info;
}

bool is_reserved(std::string_view key) noexcept {
    return key == "ts" || key == "level" || key == "event";
}

}  // namespace

Result<Level> parse_level(std::string_view text) {
    if (text == "trace") {
        return Level::Trace;
    }
    if (text == "debug") {
        return Level::Debug;
    }
    if (text == "info") {
        return Level::Info;
    }
    if (text == "warn") {
        return Level::Warn;
    }
    if (text == "error") {
        return Level::Error;
    }
    return make_error(
        ErrorCode::InvalidArgument,
        std::format("invalid log level '{}': expected error, warn, info, debug, trace", text));
}

std::string_view to_string(Level level) noexcept {
    switch (level) {
        case Level::Trace:
            return "trace";
        case Level::Debug:
            return "debug";
        case Level::Info:
            return "info";
        case Level::Warn:
            return "warn";
        case Level::Error:
            return "error";
    }
    return "info";
}

Result<Level> init(Level configured, std::optional<std::string_view> env_level) {
    Level effective = configured;
    if (env_level && !env_level->empty()) {
        auto parsed = parse_level(*env_level);
        if (!parsed) {
            return make_error(ErrorCode::InvalidArgument,
                              std::format("LOG_LEVEL: {}", parsed.error().message));
        }
        effective = *parsed;
    }

    shutdown();
    spdlog::init_thread_pool(kQueueSize, 1);
    auto sink = std::make_shared<spdlog::sinks::stderr_sink_mt>();
    g_logger =
        std::make_shared<spdlog::async_logger>(kLoggerName, std::move(sink), spdlog::thread_pool(),
                                               spdlog::async_overflow_policy::overrun_oldest);
    g_logger->set_pattern("%v");  // records are fully formatted JSON already
    g_logger->set_level(spdlog::level::trace);
    g_logger->flush_on(spdlog::level::err);
    set_level(effective);
    return effective;
}

void set_level(Level level) {
    g_level.store(static_cast<int>(level), std::memory_order_relaxed);
}

bool enabled(Level level) noexcept {
    return static_cast<int>(level) >= g_level.load(std::memory_order_relaxed);
}

std::string format_record(Level level, std::string_view event, const nlohmann::json& fields,
                          std::chrono::system_clock::time_point ts) {
    nlohmann::ordered_json record;
    record["ts"] = std::format("{:%FT%TZ}", std::chrono::floor<std::chrono::microseconds>(ts));
    record["level"] = to_string(level);
    record["event"] = event;
    if (fields.is_object()) {
        for (const auto& [key, value] : fields.items()) {
            record[is_reserved(key) ? "field." + key : key] = value;
        }
    } else if (!fields.is_null()) {
        record["fields"] = fields;
    }
    return record.dump(-1, ' ', false, nlohmann::json::error_handler_t::replace);
}

void write(Level level, std::string_view event, const nlohmann::json& fields) {
    if (!enabled(level)) {
        return;
    }
    auto line = format_record(level, event, fields, std::chrono::system_clock::now());
    if (g_logger) {
        g_logger->log(to_spdlog(level), line);
    }
}

void flush() {
    if (g_logger) {
        g_logger->flush();
    }
}

void shutdown() {
    if (g_logger) {
        g_logger->flush();
        g_logger.reset();
    }
    spdlog::shutdown();
}

std::size_t dropped_records() noexcept {
    auto pool = spdlog::thread_pool();
    return pool ? pool->overrun_counter() : 0;
}

}  // namespace hfdns::log
