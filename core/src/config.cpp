#include "hfdns/config.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <format>
#include <fstream>
#include <initializer_list>
#include <limits>
#include <set>
#include <sstream>
#include <thread>
#include <tuple>

#include <yaml-cpp/yaml.h>

#include "hfdns/duration.hpp"

namespace hfdns {

std::string_view to_string(Transport t) noexcept {
    switch (t) {
        case Transport::Udp:
            return "udp";
        case Transport::Tcp:
            return "tcp";
    }
    return "udp";
}

namespace {

struct PolicyName {
    PolicyKind kind;
    std::string_view name;
};

constexpr std::array kPolicies{
    PolicyName{.kind = PolicyKind::RoundRobin, .name = "round_robin"},
    PolicyName{.kind = PolicyKind::Weighted, .name = "weighted"},
    PolicyName{.kind = PolicyKind::LeastInflight, .name = "least_inflight"},
    PolicyName{.kind = PolicyKind::LatencyBased, .name = "latency_based"},
    PolicyName{.kind = PolicyKind::GeoAware, .name = "geo_aware"},
    PolicyName{.kind = PolicyKind::HealthAware, .name = "health_aware"},
    PolicyName{.kind = PolicyKind::Adaptive, .name = "adaptive"},
};

}  // namespace

std::string_view to_string(PolicyKind p) noexcept {
    for (const auto& entry : kPolicies) {
        if (entry.kind == p) {
            return entry.name;
        }
    }
    return "round_robin";
}

Result<PolicyKind> parse_policy(std::string_view text) {
    for (const auto& entry : kPolicies) {
        if (entry.name == text) {
            return entry.kind;
        }
    }
    return make_error(
        ErrorCode::InvalidArgument,
        std::format("unknown policy '{}': expected round_robin, weighted, "
                    "least_inflight, latency_based, geo_aware, health_aware, adaptive",
                    text));
}

unsigned detect_hardware_threads() noexcept {
    const unsigned n = std::thread::hardware_concurrency();
    return n == 0 ? 1 : n;
}

namespace {

constexpr std::uint32_t kMaxWeight = 10'000;
constexpr unsigned kMaxWorkers = 256;
constexpr auto kMinUpstreamTimeout = std::chrono::milliseconds(1);
constexpr auto kMaxUpstreamTimeout = std::chrono::seconds(60);

bool is_identifier(std::string_view s) noexcept {
    if (s.empty() || s.size() > 63) {
        return false;
    }
    auto ok = [](char c) {
        return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-';
    };
    return std::ranges::all_of(s, ok) && s.front() != '-' && s.front() != '_';
}

// Validates one YAML document against the schema, collecting every problem.
class Loader {
public:
    explicit Loader(unsigned hardware_threads) : hardware_threads_(hardware_threads) {}

    Result<Config> load(const YAML::Node& root) {
        Config cfg;
        cfg.admin.address = *IpAddress::parse("127.0.0.1");

        if (!root.IsMap()) {
            fail(root, "", "top level must be a mapping");
            return finish(std::move(cfg));
        }
        check_keys(root, "",
                   {"listeners", "workers", "admin", "logging", "regions", "backends", "routing",
                    "upstream"});

        load_listeners(root["listeners"], cfg);
        load_workers(root["workers"], cfg);
        load_admin(root["admin"], cfg);
        load_logging(root["logging"], cfg);
        load_regions(root["regions"], cfg);
        load_backends(root["backends"], cfg);
        load_routing(root["routing"], cfg);
        load_upstream(root["upstream"], cfg);
        cross_validate(cfg);
        return finish(std::move(cfg));
    }

private:
    unsigned hardware_threads_;
    std::vector<std::string> errors_;

    Result<Config> finish(Config cfg) {
        if (!errors_.empty()) {
            // Build the message first: argument evaluation order is unspecified, so
            // formatting errors_.size() alongside std::move(errors_) could read 0.
            auto message = std::format("configuration has {} error(s)", errors_.size());
            return make_error(ErrorCode::ConfigInvalid, std::move(message), std::move(errors_));
        }
        return cfg;
    }

    static std::string location(const YAML::Node& node, std::string_view path) {
        const auto mark = node.Mark();
        std::string p = path.empty() ? "<root>" : std::string(path);
        if (mark.line < 0) {
            return p;
        }
        return std::format("{} (line {})", p, mark.line + 1);
    }

    void fail(const YAML::Node& node, std::string_view path, std::string_view what) {
        errors_.push_back(std::format("{}: {}", location(node, path), what));
    }

    void fail_at(std::string_view path, std::string_view what) {
        errors_.push_back(std::format("{}: {}", path, what));
    }

    static std::string join(std::string_view parent, std::string_view child) {
        return parent.empty() ? std::string(child) : std::format("{}.{}", parent, child);
    }

    void check_keys(const YAML::Node& map, std::string_view path,
                    std::initializer_list<std::string_view> allowed) {
        for (const auto& kv : map) {
            const auto key = kv.first.as<std::string>("");
            if (std::ranges::find(allowed, key) == allowed.end()) {
                fail(kv.first, join(path, key), "unknown key");
            }
        }
    }

    bool expect_map(const YAML::Node& node, std::string_view path) {
        if (!node.IsMap()) {
            fail(node, path, "must be a mapping");
            return false;
        }
        return true;
    }

    std::optional<std::string> str(const YAML::Node& node, std::string_view path) {
        if (!node.IsScalar()) {
            fail(node, path, "must be a scalar");
            return std::nullopt;
        }
        return node.Scalar();
    }

    std::optional<std::int64_t> integer(const YAML::Node& node, std::string_view path,
                                        std::int64_t lo, std::int64_t hi) {
        std::int64_t v = 0;
        if (!node.IsScalar() || !YAML::convert<std::int64_t>::decode(node, v)) {
            fail(node, path, "must be an integer");
            return std::nullopt;
        }
        if (v < lo || v > hi) {
            fail(node, path, std::format("must be between {} and {}", lo, hi));
            return std::nullopt;
        }
        return v;
    }

    std::optional<std::uint16_t> port(const YAML::Node& node, std::string_view path) {
        auto v = integer(node, path, 1, std::numeric_limits<std::uint16_t>::max());
        return v ? std::optional<std::uint16_t>(static_cast<std::uint16_t>(*v)) : std::nullopt;
    }

    std::optional<IpAddress> address(const YAML::Node& node, std::string_view path) {
        auto s = str(node, path);
        if (!s) {
            return std::nullopt;
        }
        auto addr = IpAddress::parse(*s);
        if (!addr) {
            fail(node, path, addr.error().message);
            return std::nullopt;
        }
        return *addr;
    }

    std::optional<std::string> identifier(const YAML::Node& node, std::string_view path) {
        auto s = str(node, path);
        if (s && !is_identifier(*s)) {
            fail(node, path, std::format("'{}' must match [a-z0-9][a-z0-9_-]{{0,62}}", *s));
            return std::nullopt;
        }
        return s;
    }

    void require(const YAML::Node& map, std::string_view path, std::string_view key) {
        if (!map[std::string(key)]) {
            fail(map, join(path, key), "is required");
        }
    }

    void load_listeners(const YAML::Node& node, Config& cfg) {
        if (!node) {
            fail_at("listeners", "is required (at least one listener)");
            return;
        }
        if (!node.IsSequence() || node.size() == 0) {
            fail(node, "listeners", "must be a non-empty list");
            return;
        }
        for (std::size_t i = 0; i < node.size(); ++i) {
            const auto item = node[i];
            const auto path = std::format("listeners[{}]", i);
            if (!expect_map(item, path)) {
                continue;
            }
            check_keys(item, path, {"address", "port", "transport"});
            require(item, path, "address");
            require(item, path, "port");
            ListenerConfig l;
            bool ok = true;
            if (item["address"]) {
                auto a = address(item["address"], join(path, "address"));
                ok &= a.has_value();
                l.address = a.value_or(IpAddress{});
            }
            if (item["port"]) {
                auto p = port(item["port"], join(path, "port"));
                ok &= p.has_value();
                l.port = p.value_or(0);
            }
            if (item["transport"]) {
                const auto t = str(item["transport"], join(path, "transport"));
                if (t == "udp") {
                    l.transport = Transport::Udp;
                } else if (t == "tcp") {
                    l.transport = Transport::Tcp;
                } else if (t) {
                    fail(item["transport"], join(path, "transport"), "must be udp or tcp");
                    ok = false;
                }
            }
            if (ok && item["address"] && item["port"]) {
                cfg.listeners.push_back(l);
            }
        }
    }

    void load_workers(const YAML::Node& node, Config& cfg) {
        if (!node || (node.IsScalar() && node.Scalar() == "auto")) {
            // Leave one hardware thread for the control/admin threads and the OS.
            cfg.workers =
                std::clamp(hardware_threads_ > 1 ? hardware_threads_ - 1 : 1U, 1U, kMaxWorkers);
            cfg.workers_auto = true;
            return;
        }
        if (auto v = integer(node, "workers", 1, kMaxWorkers)) {
            cfg.workers = static_cast<unsigned>(*v);
        }
    }

    void load_admin(const YAML::Node& node, Config& cfg) {
        if (!node || !expect_map(node, "admin")) {
            return;
        }
        check_keys(node, "admin", {"address", "port"});
        if (node["address"]) {
            if (auto a = address(node["address"], "admin.address")) {
                cfg.admin.address = *a;
            }
        }
        if (node["port"]) {
            if (auto p = port(node["port"], "admin.port")) {
                cfg.admin.port = *p;
            }
        }
    }

    void load_logging(const YAML::Node& node, Config& cfg) {
        if (!node || !expect_map(node, "logging")) {
            return;
        }
        check_keys(node, "logging", {"level"});
        if (node["level"]) {
            if (auto s = str(node["level"], "logging.level")) {
                auto lvl = log::parse_level(*s);
                if (lvl) {
                    cfg.logging.level = *lvl;
                } else {
                    fail(node["level"], "logging.level", lvl.error().message);
                }
            }
        }
    }

    void load_regions(const YAML::Node& node, Config& cfg) {
        if (!node) {
            return;
        }
        if (!node.IsSequence()) {
            fail(node, "regions", "must be a list");
            return;
        }
        for (std::size_t i = 0; i < node.size(); ++i) {
            const auto item = node[i];
            const auto path = std::format("regions[{}]", i);
            if (!expect_map(item, path)) {
                continue;
            }
            check_keys(item, path, {"name", "client_cidrs"});
            require(item, path, "name");
            require(item, path, "client_cidrs");
            RegionConfig r;
            if (item["name"]) {
                r.name = identifier(item["name"], join(path, "name")).value_or("");
            }
            const auto cidrs = item["client_cidrs"];
            if (cidrs && (!cidrs.IsSequence() || cidrs.size() == 0)) {
                fail(cidrs, join(path, "client_cidrs"), "must be a non-empty list");
            } else if (cidrs) {
                for (std::size_t j = 0; j < cidrs.size(); ++j) {
                    const auto cpath = std::format("{}.client_cidrs[{}]", path, j);
                    if (auto s = str(cidrs[j], cpath)) {
                        auto c = Cidr::parse(*s);
                        if (c) {
                            r.client_cidrs.push_back(*c);
                        } else {
                            fail(cidrs[j], cpath, c.error().message);
                        }
                    }
                }
            }
            if (!r.name.empty()) {
                cfg.regions.push_back(std::move(r));
            }
        }
    }

    void load_backends(const YAML::Node& node, Config& cfg) {
        if (!node) {
            fail_at("backends", "is required (at least one backend)");
            return;
        }
        if (!node.IsSequence() || node.size() == 0) {
            fail(node, "backends", "must be a non-empty list");
            return;
        }
        for (std::size_t i = 0; i < node.size(); ++i) {
            const auto item = node[i];
            const auto path = std::format("backends[{}]", i);
            if (!expect_map(item, path)) {
                continue;
            }
            check_keys(item, path, {"name", "address", "port", "weight", "site"});
            require(item, path, "name");
            require(item, path, "address");
            require(item, path, "site");
            BackendConfig b;
            bool ok = true;
            if (item["name"]) {
                auto n = identifier(item["name"], join(path, "name"));
                ok &= n.has_value();
                b.name = n.value_or("");
            }
            if (item["address"]) {
                auto a = address(item["address"], join(path, "address"));
                ok &= a.has_value();
                b.address = a.value_or(IpAddress{});
            }
            if (item["port"]) {
                auto p = port(item["port"], join(path, "port"));
                ok &= p.has_value();
                b.port = p.value_or(0);
            }
            if (item["weight"]) {
                auto w = integer(item["weight"], join(path, "weight"), 1, kMaxWeight);
                ok &= w.has_value();
                b.weight = static_cast<std::uint32_t>(w.value_or(1));
            }
            if (item["site"]) {
                auto s = identifier(item["site"], join(path, "site"));
                ok &= s.has_value();
                b.site = s.value_or("");
            }
            if (ok && item["name"] && item["address"] && item["site"]) {
                cfg.backends.push_back(std::move(b));
            }
        }
    }

    void load_routing(const YAML::Node& node, Config& cfg) {
        if (!node || !expect_map(node, "routing")) {
            return;
        }
        check_keys(node, "routing", {"policy"});
        if (node["policy"]) {
            if (auto s = str(node["policy"], "routing.policy")) {
                auto p = parse_policy(*s);
                if (p) {
                    cfg.routing.policy = *p;
                } else {
                    fail(node["policy"], "routing.policy", p.error().message);
                }
            }
        }
    }

    void load_upstream(const YAML::Node& node, Config& cfg) {
        if (!node || !expect_map(node, "upstream")) {
            return;
        }
        check_keys(node, "upstream", {"timeout"});
        if (node["timeout"]) {
            if (auto s = str(node["timeout"], "upstream.timeout")) {
                auto d = parse_duration(*s);
                if (!d) {
                    fail(node["timeout"], "upstream.timeout", d.error().message);
                } else if (*d < kMinUpstreamTimeout || *d > kMaxUpstreamTimeout) {
                    fail(node["timeout"], "upstream.timeout", "must be between 1ms and 60s");
                } else {
                    cfg.upstream.timeout = *d;
                }
            }
        }
    }

    void cross_validate(const Config& cfg) {
        std::set<std::tuple<std::string, std::uint16_t, Transport>> listeners;
        for (const auto& l : cfg.listeners) {
            if (!listeners.emplace(l.address.to_string(), l.port, l.transport).second) {
                fail_at("listeners",
                        std::format("duplicate listener {}:{}/{}", l.address.to_string(), l.port,
                                    to_string(l.transport)));
            }
            // The admin endpoint is TCP, so it only collides with TCP listeners.
            if (l.transport == Transport::Tcp && l.port == cfg.admin.port &&
                l.address == cfg.admin.address) {
                fail_at("admin", std::format("admin endpoint {}:{} collides with a TCP listener",
                                             l.address.to_string(), l.port));
            }
        }

        std::set<std::string> names;
        for (const auto& r : cfg.regions) {
            if (!names.insert(r.name).second) {
                fail_at("regions", std::format("duplicate region name '{}'", r.name));
            }
        }
        // Nested prefixes are fine (longest match wins); an identical prefix in two
        // regions has no correct answer.
        for (std::size_t i = 0; i < cfg.regions.size(); ++i) {
            for (std::size_t j = i + 1; j < cfg.regions.size(); ++j) {
                for (const auto& a : cfg.regions[i].client_cidrs) {
                    for (const auto& b : cfg.regions[j].client_cidrs) {
                        if (a == b) {
                            fail_at("regions",
                                    std::format("CIDR {} is claimed by both '{}' and '{}'",
                                                a.to_string(), cfg.regions[i].name,
                                                cfg.regions[j].name));
                        }
                    }
                }
            }
        }

        std::set<std::string> backend_names;
        std::set<std::pair<std::string, std::uint16_t>> endpoints;
        for (const auto& b : cfg.backends) {
            if (!backend_names.insert(b.name).second) {
                fail_at("backends", std::format("duplicate backend name '{}'", b.name));
            }
            if (!endpoints.emplace(b.address.to_string(), b.port).second) {
                fail_at("backends", std::format("duplicate backend endpoint {}:{}",
                                                b.address.to_string(), b.port));
            }
        }
    }
};

}  // namespace

Result<Config> load_config_string(std::string_view yaml, unsigned hardware_threads) {
    YAML::Node root;
    try {
        root = YAML::Load(std::string(yaml));
    } catch (const YAML::ParserException& e) {
        return make_error(
            ErrorCode::ConfigInvalid, "configuration is not valid YAML",
            {std::format("line {}, column {}: {}", e.mark.line + 1, e.mark.column + 1, e.msg)});
    }
    return Loader(hardware_threads).load(root);
}

Result<Config> load_config_file(const std::filesystem::path& path, unsigned hardware_threads) {
    const std::ifstream in(path);
    if (!in) {
        return make_error(ErrorCode::IoError,
                          std::format("cannot open config file '{}'", path.string()));
    }
    std::ostringstream buf;
    buf << in.rdbuf();
    auto cfg = load_config_string(buf.str(), hardware_threads);
    if (!cfg) {
        cfg.error().message = std::format("{}: {}", path.string(), cfg.error().message);
    }
    return cfg;
}

}  // namespace hfdns
