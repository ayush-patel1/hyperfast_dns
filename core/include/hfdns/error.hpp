#pragma once

#include <cstdint>
#include <expected>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace hfdns {

enum class ErrorCode : std::uint8_t {
    InvalidArgument,
    ConfigInvalid,
    IoError,
    NetworkError,
    Internal,
};

std::string_view to_string(ErrorCode code) noexcept;

// `details` carries one entry per independent problem (e.g. every invalid
// config field), so callers can report all of them instead of only the first.
struct Error {
    ErrorCode code;
    std::string message;
    std::vector<std::string> details;

    Error(ErrorCode c, std::string msg, std::vector<std::string> d = {})
        : code(c), message(std::move(msg)), details(std::move(d)) {}

    std::string to_string() const;
};

template <typename T>
using Result = std::expected<T, Error>;

using Status = std::expected<void, Error>;

inline std::unexpected<Error> make_error(ErrorCode code, std::string message,
                                         std::vector<std::string> details = {}) {
    return std::unexpected<Error>(Error(code, std::move(message), std::move(details)));
}

}  // namespace hfdns
