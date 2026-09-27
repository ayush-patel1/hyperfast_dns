#include "hfdns/log.hpp"

#include <gtest/gtest.h>
#include <nlohmann/json.hpp>

namespace hfdns::log {
namespace {

std::chrono::system_clock::time_point fixed_time() {
    using namespace std::chrono;
    return sys_days{year{2026} / 9 / 27} + hours(10) + minutes(15) + seconds(3) + microseconds(42);
}

TEST(LogLevel, ParsesExactlyTheDocumentedLevels) {
    EXPECT_EQ(*parse_level("error"), Level::Error);
    EXPECT_EQ(*parse_level("warn"), Level::Warn);
    EXPECT_EQ(*parse_level("info"), Level::Info);
    EXPECT_EQ(*parse_level("debug"), Level::Debug);
    EXPECT_EQ(*parse_level("trace"), Level::Trace);
    EXPECT_FALSE(parse_level("INFO"));
    EXPECT_FALSE(parse_level("warning"));
    EXPECT_FALSE(parse_level(""));
}

TEST(LogLevel, EnabledRespectsThreshold) {
    set_level(Level::Warn);
    EXPECT_FALSE(enabled(Level::Info));
    EXPECT_TRUE(enabled(Level::Warn));
    EXPECT_TRUE(enabled(Level::Error));
    set_level(Level::Info);
}

TEST(LogInit, EnvOverridesConfigAndInvalidEnvIsAnError) {
    auto lvl = init(Level::Info, "debug");
    ASSERT_TRUE(lvl);
    EXPECT_EQ(*lvl, Level::Debug);
    EXPECT_FALSE(init(Level::Info, "loud"));
    auto unset = init(Level::Warn, std::nullopt);
    ASSERT_TRUE(unset);
    EXPECT_EQ(*unset, Level::Warn);
    shutdown();
    set_level(Level::Info);
}

TEST(FormatRecord, IsOneValidJsonObjectWithFixedKeyOrder) {
    const auto line = format_record(Level::Warn, "health_transition",
                                    {{"backend", "pop-india"}, {"to", "DEGRADED"}}, fixed_time());
    EXPECT_EQ(line.find('\n'), std::string::npos);
    EXPECT_TRUE(line.starts_with(
        R"({"ts":"2026-09-27T10:15:03.000042Z","level":"warn","event":"health_transition")"))
        << line;
    const auto j = nlohmann::json::parse(line);
    EXPECT_EQ(j["backend"], "pop-india");
    EXPECT_EQ(j["to"], "DEGRADED");
}

TEST(FormatRecord, EscapesHostileContent) {
    const auto line =
        format_record(Level::Info, "evt", {{"msg", "quote\" newline\n brace}"}}, fixed_time());
    const auto j = nlohmann::json::parse(line);  // throws if escaping were wrong
    EXPECT_EQ(j["msg"], "quote\" newline\n brace}");
}

TEST(FormatRecord, ReservedKeysCannotBeOverwritten) {
    const auto j = nlohmann::json::parse(
        format_record(Level::Info, "real", {{"event", "fake"}, {"level", "error"}}, fixed_time()));
    EXPECT_EQ(j["event"], "real");
    EXPECT_EQ(j["level"], "info");
    EXPECT_EQ(j["field.event"], "fake");
    EXPECT_EQ(j["field.level"], "error");
}

TEST(FormatRecord, InvalidUtf8IsReplacedNotThrown) {
    const std::string bad = "ok\xff\xfe";
    std::string line;
    EXPECT_NO_THROW(line = format_record(Level::Info, "evt", {{"v", bad}}, fixed_time()));
    EXPECT_TRUE(nlohmann::json::accept(line)) << line;
}

}  // namespace
}  // namespace hfdns::log
