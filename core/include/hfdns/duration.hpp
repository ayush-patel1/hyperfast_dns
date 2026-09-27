#pragma once

#include <chrono>
#include <string>
#include <string_view>

#include "hfdns/error.hpp"

namespace hfdns {

// Parses "250us", "800ms", "2s", "1m" into microseconds. A unit is mandatory,
// so a bare "800" can never be silently read as the wrong unit.
Result<std::chrono::microseconds> parse_duration(std::string_view text);

std::string format_duration(std::chrono::microseconds d);

}  // namespace hfdns
