#pragma once

#include <array>
#include <cstdint>
#include <string>
#include <string_view>

#include "hfdns/error.hpp"

namespace hfdns {

enum class AddressFamily : std::uint8_t { V4, V6 };

// Plain value type; IPv4 uses the first 4 bytes of `bytes`.
struct IpAddress {
    AddressFamily family = AddressFamily::V4;
    std::array<std::uint8_t, 16> bytes{};

    static Result<IpAddress> parse(std::string_view text);
    std::string to_string() const;
    unsigned bit_width() const noexcept { return family == AddressFamily::V4 ? 32U : 128U; }

    friend bool operator==(const IpAddress&, const IpAddress&) = default;
};

struct Cidr {
    IpAddress network;  // host bits are always zero
    std::uint8_t prefix_len = 0;

    // Rejects prefixes longer than the address width and networks with host bits set,
    // because "10.0.0.1/8" is almost always a configuration mistake.
    static Result<Cidr> parse(std::string_view text);
    bool contains(const IpAddress& addr) const noexcept;
    std::string to_string() const;

    friend bool operator==(const Cidr&, const Cidr&) = default;
};

}  // namespace hfdns
