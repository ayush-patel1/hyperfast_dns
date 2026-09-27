#include "hfdns/duration.hpp"

#include <charconv>
#include <cstdint>
#include <format>
#include <limits>

namespace hfdns {

Result<std::chrono::microseconds> parse_duration(std::string_view text) {
    std::uint64_t value = 0;
    const auto [ptr, ec] = std::from_chars(text.data(), text.data() + text.size(), value);
    if (ec != std::errc{} || ptr == text.data()) {
        return make_error(ErrorCode::InvalidArgument,
                          std::format("invalid duration '{}': expected e.g. 800ms, 2s", text));
    }
    const std::string_view unit(ptr, static_cast<std::size_t>(text.data() + text.size() - ptr));

    std::uint64_t scale = 0;
    if (unit == "us") {
        scale = 1;
    } else if (unit == "ms") {
        scale = 1'000;
    } else if (unit == "s") {
        scale = 1'000'000;
    } else if (unit == "m") {
        scale = 60'000'000;
    } else {
        return make_error(
            ErrorCode::InvalidArgument,
            std::format("invalid duration '{}': unit must be one of us, ms, s, m", text));
    }
    constexpr auto kMax = static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max());
    if (value > kMax / scale) {
        return make_error(ErrorCode::InvalidArgument,
                          std::format("invalid duration '{}': too large", text));
    }
    return std::chrono::microseconds(static_cast<std::int64_t>(value * scale));
}

std::string format_duration(std::chrono::microseconds d) {
    const auto us = d.count();
    if (us % 1'000'000 == 0) {
        return std::format("{}s", us / 1'000'000);
    }
    if (us % 1'000 == 0) {
        return std::format("{}ms", us / 1'000);
    }
    return std::format("{}us", us);
}

}  // namespace hfdns
