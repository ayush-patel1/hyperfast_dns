#pragma once

#include <optional>
#include <span>
#include <string>
#include <string_view>

#include "hfdns/error.hpp"

namespace hfdns {

struct CliOptions {
    std::string config_path;
    bool check_config = false;
    bool show_version = false;
    bool show_help = false;
    std::optional<std::string> log_level;  // overrides config; LOG_LEVEL env overrides both
};

// Process exit codes (stable; scripts depend on them).
inline constexpr int kExitOk = 0;
inline constexpr int kExitRuntimeError = 1;
inline constexpr int kExitUsage = 2;
inline constexpr int kExitConfigInvalid = 3;

Result<CliOptions> parse_cli(std::span<const std::string_view> args);
std::string_view cli_usage() noexcept;

}  // namespace hfdns
