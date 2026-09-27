#pragma once

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "hfdns/error.hpp"
#include "hfdns/log.hpp"
#include "hfdns/net.hpp"

namespace hfdns {

enum class Transport : std::uint8_t { Udp, Tcp };

enum class PolicyKind : std::uint8_t {
    RoundRobin,
    Weighted,
    LeastInflight,
    LatencyBased,
    GeoAware,
    HealthAware,
    Adaptive,
};

std::string_view to_string(Transport t) noexcept;
std::string_view to_string(PolicyKind p) noexcept;
Result<PolicyKind> parse_policy(std::string_view text);

struct ListenerConfig {
    IpAddress address;
    std::uint16_t port = 0;
    Transport transport = Transport::Udp;
};

struct AdminConfig {
    IpAddress address;  // default 127.0.0.1, set by the loader
    std::uint16_t port = 8053;
};

struct LoggingConfig {
    log::Level level = log::Level::Info;
};

// A client population (e.g. "india"), identified by source CIDRs.
struct RegionConfig {
    std::string name;
    std::vector<Cidr> client_cidrs;
};

// `site` names where the backend runs (e.g. "singapore"). It is deliberately a
// separate namespace from client regions: the region->site affinity is
// configured, never inferred from names (ARCHITECTURE §11).
struct BackendConfig {
    std::string name;
    IpAddress address;
    std::uint16_t port = 53;
    std::uint32_t weight = 1;
    std::string site;
};

struct RoutingConfig {
    PolicyKind policy = PolicyKind::RoundRobin;
};

struct UpstreamConfig {
    std::chrono::microseconds timeout{std::chrono::milliseconds(800)};
};

struct Config {
    std::vector<ListenerConfig> listeners;
    unsigned workers = 1;  // resolved: "auto" becomes a concrete number at load time
    bool workers_auto = false;
    AdminConfig admin;
    LoggingConfig logging;
    std::vector<RegionConfig> regions;
    std::vector<BackendConfig> backends;
    RoutingConfig routing;
    UpstreamConfig upstream;
};

// `hardware_threads` is injected so "workers: auto" is deterministic in tests.
Result<Config> load_config_string(std::string_view yaml, unsigned hardware_threads);
Result<Config> load_config_file(const std::filesystem::path& path, unsigned hardware_threads);

unsigned detect_hardware_threads() noexcept;

}  // namespace hfdns
