#include "hfdns/net.hpp"

#include <arpa/inet.h>
#include <charconv>
#include <cstring>
#include <format>

namespace hfdns {

Result<IpAddress> IpAddress::parse(std::string_view text) {
    // inet_pton needs a NUL-terminated string; 45 chars covers the longest IPv6 text form.
    if (text.empty() || text.size() > INET6_ADDRSTRLEN) {
        return make_error(ErrorCode::InvalidArgument, std::format("invalid IP address '{}'", text));
    }
    std::array<char, INET6_ADDRSTRLEN + 1> buf{};
    std::memcpy(buf.data(), text.data(), text.size());

    IpAddress addr;
    if (inet_pton(AF_INET, buf.data(), addr.bytes.data()) == 1) {
        addr.family = AddressFamily::V4;
        return addr;
    }
    if (inet_pton(AF_INET6, buf.data(), addr.bytes.data()) == 1) {
        addr.family = AddressFamily::V6;
        return addr;
    }
    return make_error(ErrorCode::InvalidArgument, std::format("invalid IP address '{}'", text));
}

std::string IpAddress::to_string() const {
    std::array<char, INET6_ADDRSTRLEN> buf{};
    const int af = family == AddressFamily::V4 ? AF_INET : AF_INET6;
    if (inet_ntop(af, bytes.data(), buf.data(), buf.size()) == nullptr) {
        return "<invalid>";
    }
    return {buf.data()};
}

namespace {

bool prefix_matches(const IpAddress& a, const IpAddress& b, unsigned prefix_len) noexcept {
    const unsigned full_bytes = prefix_len / 8;
    if (std::memcmp(a.bytes.data(), b.bytes.data(), full_bytes) != 0) {
        return false;
    }
    const unsigned rem_bits = prefix_len % 8;
    if (rem_bits == 0) {
        return true;
    }
    const auto mask = static_cast<std::uint8_t>(0xFFU << (8U - rem_bits));
    return (a.bytes[full_bytes] & mask) == (b.bytes[full_bytes] & mask);
}

bool host_bits_zero(const IpAddress& a, unsigned prefix_len) noexcept {
    for (unsigned bit = prefix_len; bit < a.bit_width(); ++bit) {
        if (((a.bytes[bit / 8] >> (7U - bit % 8)) & 1U) != 0) {
            return false;
        }
    }
    return true;
}

}  // namespace

Result<Cidr> Cidr::parse(std::string_view text) {
    const auto slash = text.find('/');
    if (slash == std::string_view::npos) {
        return make_error(ErrorCode::InvalidArgument,
                          std::format("invalid CIDR '{}': missing '/prefix'", text));
    }
    auto addr = IpAddress::parse(text.substr(0, slash));
    if (!addr) {
        return make_error(ErrorCode::InvalidArgument,
                          std::format("invalid CIDR '{}': bad address", text));
    }
    const auto len_text = text.substr(slash + 1);
    unsigned len = 0;
    const auto [ptr, ec] = std::from_chars(len_text.data(), len_text.data() + len_text.size(), len);
    if (ec != std::errc{} || ptr != len_text.data() + len_text.size() || len_text.empty()) {
        return make_error(ErrorCode::InvalidArgument,
                          std::format("invalid CIDR '{}': bad prefix length", text));
    }
    if (len > addr->bit_width()) {
        return make_error(
            ErrorCode::InvalidArgument,
            std::format("invalid CIDR '{}': prefix longer than {} bits", text, addr->bit_width()));
    }
    if (!host_bits_zero(*addr, len)) {
        return make_error(ErrorCode::InvalidArgument,
                          std::format("invalid CIDR '{}': host bits set", text));
    }
    return Cidr{.network = *addr, .prefix_len = static_cast<std::uint8_t>(len)};
}

bool Cidr::contains(const IpAddress& addr) const noexcept {
    return addr.family == network.family && prefix_matches(network, addr, prefix_len);
}

std::string Cidr::to_string() const {
    return std::format("{}/{}", network.to_string(), prefix_len);
}

}  // namespace hfdns
