#include "hfdns/cli.hpp"

#include <vector>

#include <gtest/gtest.h>

namespace hfdns {
namespace {

Result<CliOptions> parse(std::vector<std::string_view> args) {
    return parse_cli(args);
}

TEST(Cli, ParsesConfigAndFlags) {
    auto o = parse({"--config", "a.yaml", "--check-config", "--log-level", "debug"});
    ASSERT_TRUE(o);
    EXPECT_EQ(o->config_path, "a.yaml");
    EXPECT_TRUE(o->check_config);
    EXPECT_EQ(o->log_level, "debug");
}

TEST(Cli, AcceptsShortAndEqualsForms) {
    EXPECT_EQ(parse({"-c", "x.yaml"})->config_path, "x.yaml");
    EXPECT_EQ(parse({"--config=y.yaml"})->config_path, "y.yaml");
}

TEST(Cli, HelpAndVersionDoNotNeedConfig) {
    EXPECT_TRUE(parse({"--help"})->show_help);
    EXPECT_TRUE(parse({"-V"})->show_version);
}

TEST(Cli, RejectsMissingConfigUnknownArgsAndMissingValues) {
    EXPECT_FALSE(parse({}));
    EXPECT_FALSE(parse({"--check-config"}));
    EXPECT_FALSE(parse({"--config", "a.yaml", "--frobnicate"}));
    EXPECT_FALSE(parse({"--config"}));
    EXPECT_FALSE(parse({"--config", "--check-config"}));
    EXPECT_FALSE(parse({"--config", "a.yaml", "--log-level"}));
}

}  // namespace
}  // namespace hfdns
