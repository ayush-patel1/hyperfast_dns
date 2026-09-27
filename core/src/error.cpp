#include "hfdns/error.hpp"

namespace hfdns {

std::string_view to_string(ErrorCode code) noexcept {
    switch (code) {
        case ErrorCode::InvalidArgument:
            return "invalid_argument";
        case ErrorCode::ConfigInvalid:
            return "config_invalid";
        case ErrorCode::IoError:
            return "io_error";
        case ErrorCode::NetworkError:
            return "network_error";
        case ErrorCode::Internal:
            return "internal";
    }
    return "unknown";
}

std::string Error::to_string() const {
    std::string out = message;
    for (const auto& d : details) {
        out += "\n  - ";
        out += d;
    }
    return out;
}

}  // namespace hfdns
