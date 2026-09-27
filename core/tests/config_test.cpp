#include "hfdns/config.hpp"

#include <algorithm>
#include <format>
#include <string>

#include <gtest/gtest.h>

namespace hfdns {
namespace {

constexpr unsigned kHwThreads = 8;

constexpr std::string_view kMinimal = R"(
listeners:
  - { address: 127.0.0.1, port: 5353 }
backends:
  - { name: a, address: 127.0.0.1, site: india }
)";

Result<Config> load(std::string_view yaml) {
    return load_config_string(yaml, kHwThreads);
}

// Every detail line must be present; asserting on substrings keeps tests
// robust to wording while still pinning which field was reported.
void expect_errors(const Result<Config>& r, std::initializer_list<std::string_view> fragments) {
    ASSERT_FALSE(r) << "expected config to be rejected";
    EXPECT_EQ(r.error().code, ErrorCode::ConfigInvalid);
    for (auto frag : fragments) {
        const bool found = std::ranges::any_of(r.error().details, [&](const std::string& d) {
            return d.find(frag) != std::string::npos;
        });
        EXPECT_TRUE(found) << "missing error containing '" << frag << "' in:\n"
                           << r.error().to_string();
    }
}

TEST(Config, RepoDevConfigLoads) {
    auto cfg = load_config_file(std::string(HFDNS_REPO_CONFIG_DIR) + "/dev.yaml", kHwThreads);
    ASSERT_TRUE(cfg) << cfg.error().to_string();
    EXPECT_EQ(cfg->listeners.size(), 1U);
    EXPECT_EQ(cfg->workers, 2U);
    EXPECT_EQ(cfg->backends.size(), 4U);
    EXPECT_EQ(cfg->regions.size(), 4U);
    EXPECT_EQ(cfg->backends[0].name, "pop-india");
    EXPECT_EQ(cfg->backends[0].weight, 4U);
    EXPECT_EQ(cfg->routing.policy, PolicyKind::RoundRobin);
    EXPECT_EQ(cfg->upstream.timeout, std::chrono::milliseconds(800));
}

TEST(Config, MinimalConfigGetsDocumentedDefaults) {
    auto cfg = load(kMinimal);
    ASSERT_TRUE(cfg) << cfg.error().to_string();
    EXPECT_EQ(cfg->listeners[0].transport, Transport::Udp);
    EXPECT_TRUE(cfg->workers_auto);
    EXPECT_EQ(cfg->workers, kHwThreads - 1);
    EXPECT_EQ(cfg->admin.address.to_string(), "127.0.0.1");
    EXPECT_EQ(cfg->admin.port, 8053);
    EXPECT_EQ(cfg->logging.level, log::Level::Info);
    EXPECT_EQ(cfg->backends[0].port, 53);
    EXPECT_EQ(cfg->backends[0].weight, 1U);
    EXPECT_EQ(cfg->routing.policy, PolicyKind::RoundRobin);
    EXPECT_EQ(cfg->upstream.timeout, std::chrono::milliseconds(800));
}

TEST(Config, AutoWorkersNeverDropsBelowOne) {
    auto cfg = load_config_string(kMinimal, 1);
    ASSERT_TRUE(cfg);
    EXPECT_EQ(cfg->workers, 1U);
}

TEST(Config, AllPoliciesParse) {
    for (auto name : {"round_robin", "weighted", "least_inflight", "latency_based", "geo_aware",
                      "health_aware", "adaptive"}) {
        auto p = parse_policy(name);
        ASSERT_TRUE(p) << name;
        EXPECT_EQ(to_string(*p), name);
    }
    EXPECT_FALSE(parse_policy("random"));
}

TEST(Config, MissingRequiredSections) {
    expect_errors(load("workers: 2\n"), {"listeners: is required", "backends: is required"});
}

TEST(Config, UnknownKeysAreRejectedWithLineNumbers) {
    expect_errors(load(std::string(kMinimal) + "routng:\n  policy: weighted\n"),
                  {"routng (line 6): unknown key"});
    expect_errors(
        load(R"(
listeners:
  - { address: 127.0.0.1, port: 5353, proto: udp }
backends:
  - { name: a, address: 127.0.0.1, site: india, wieght: 3 }
)"),
        {"listeners[0].proto (line 3): unknown key", "backends[0].wieght (line 5): unknown key"});
}

TEST(Config, FieldValueValidation) {
    expect_errors(load(R"(
listeners:
  - { address: 127.0.0.300, port: 70000, transport: sctp }
workers: 0
admin: { port: 0 }
logging: { level: loud }
backends:
  - { name: Bad Name, address: nope, port: -1, weight: 0, site: india }
routing: { policy: random }
upstream: { timeout: 800 }
)"),
                  {"listeners[0].address", "listeners[0].port", "listeners[0].transport", "workers",
                   "admin.port", "logging.level", "backends[0].name", "backends[0].address",
                   "backends[0].port", "backends[0].weight", "routing.policy", "upstream.timeout"});
}

TEST(Config, AllErrorsReportedNotJustFirst) {
    auto r = load(R"(
listeners:
  - { address: bad, port: 1 }
backends:
  - { name: a, address: bad, site: india }
routing: { policy: nope }
)");
    ASSERT_FALSE(r);
    EXPECT_GE(r.error().details.size(), 3U);
    EXPECT_EQ(r.error().message,
              std::format("configuration has {} error(s)", r.error().details.size()));
}

TEST(Config, TimeoutBounds) {
    expect_errors(load(std::string(kMinimal) + "upstream: { timeout: 500us }\n"),
                  {"between 1ms and 60s"});
    expect_errors(load(std::string(kMinimal) + "upstream: { timeout: 2m }\n"),
                  {"between 1ms and 60s"});
}

TEST(Config, CrossValidationDuplicates) {
    expect_errors(load(R"(
listeners:
  - { address: 127.0.0.1, port: 5353 }
  - { address: 127.0.0.1, port: 5353 }
backends:
  - { name: a, address: 127.0.0.1, port: 5401, site: x }
  - { name: a, address: 127.0.0.1, port: 5401, site: y }
regions:
  - { name: r1, client_cidrs: [10.0.0.0/8] }
  - { name: r1, client_cidrs: [10.0.0.0/8] }
)"),
                  {"duplicate listener", "duplicate backend name 'a'",
                   "duplicate backend endpoint 127.0.0.1:5401", "duplicate region name 'r1'",
                   "CIDR 10.0.0.0/8 is claimed by both"});
}

TEST(Config, NestedRegionCidrsAreAllowed) {
    auto cfg = load(std::string(kMinimal) + R"(
regions:
  - { name: wide,   client_cidrs: [10.0.0.0/8] }
  - { name: narrow, client_cidrs: [10.1.0.0/16] }
)");
    ASSERT_TRUE(cfg) << cfg.error().to_string();
}

TEST(Config, AdminCollidesOnlyWithTcpListener) {
    const auto base = R"(
backends:
  - { name: a, address: 127.0.0.1, site: x }
admin: { address: 127.0.0.1, port: 9000 }
listeners:
  - { address: 127.0.0.1, port: 9000, transport: )";
    EXPECT_TRUE(load(std::string(base) + "udp }\n"));
    expect_errors(load(std::string(base) + "tcp }\n"), {"collides with a TCP listener"});
}

TEST(Config, InvalidYamlAndWrongShapes) {
    auto r = load("listeners: [ {address: 1\n");
    ASSERT_FALSE(r);
    EXPECT_EQ(r.error().code, ErrorCode::ConfigInvalid);
    EXPECT_NE(r.error().details.at(0).find("line"), std::string::npos);

    expect_errors(load("- just\n- a list\n"), {"top level must be a mapping"});
    expect_errors(load("listeners: {}\nbackends: 3\n"),
                  {"listeners (line 1): must be a non-empty list",
                   "backends (line 2): must be a non-empty list"});
    expect_errors(load(""), {"top level must be a mapping"});
}

TEST(Config, MissingFileIsIoError) {
    auto r = load_config_file("/nonexistent/hfdns.yaml", kHwThreads);
    ASSERT_FALSE(r);
    EXPECT_EQ(r.error().code, ErrorCode::IoError);
}

}  // namespace
}  // namespace hfdns
