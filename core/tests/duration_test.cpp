#include "hfdns/duration.hpp"

#include <gtest/gtest.h>

namespace hfdns {
namespace {

using std::chrono::microseconds;

TEST(Duration, ParsesAllUnits) {
    EXPECT_EQ(*parse_duration("250us"), microseconds(250));
    EXPECT_EQ(*parse_duration("800ms"), microseconds(800'000));
    EXPECT_EQ(*parse_duration("2s"), microseconds(2'000'000));
    EXPECT_EQ(*parse_duration("1m"), microseconds(60'000'000));
    EXPECT_EQ(*parse_duration("0ms"), microseconds(0));
}

TEST(Duration, RequiresUnitAndRejectsJunk) {
    for (const auto* text : {"800", "ms", "", "1.5s", "-1s", "10 ms", "5h", "1sx"}) {
        EXPECT_FALSE(parse_duration(text)) << text;
    }
}

TEST(Duration, RejectsOverflow) {
    EXPECT_FALSE(parse_duration("99999999999999999m"));
}

TEST(Duration, FormatsWithLargestExactUnit) {
    EXPECT_EQ(format_duration(microseconds(2'000'000)), "2s");
    EXPECT_EQ(format_duration(microseconds(800'000)), "800ms");
    EXPECT_EQ(format_duration(microseconds(1'500)), "1500us");
}

}  // namespace
}  // namespace hfdns
