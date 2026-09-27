#include "hfdns/net.hpp"

#include <gtest/gtest.h>

namespace hfdns {
namespace {

TEST(IpAddress, ParsesV4AndV6RoundTrip) {
    auto v4 = IpAddress::parse("192.0.2.10");
    ASSERT_TRUE(v4);
    EXPECT_EQ(v4->family, AddressFamily::V4);
    EXPECT_EQ(v4->to_string(), "192.0.2.10");

    auto v6 = IpAddress::parse("2001:db8::1");
    ASSERT_TRUE(v6);
    EXPECT_EQ(v6->family, AddressFamily::V6);
    EXPECT_EQ(v6->to_string(), "2001:db8::1");
}

TEST(IpAddress, RejectsGarbage) {
    for (const auto* text : {"", "256.1.1.1", "1.2.3", "localhost", "2001:::1", "1.2.3.4 "}) {
        EXPECT_FALSE(IpAddress::parse(text)) << text;
    }
}

TEST(Cidr, ContainsRespectsPrefixAndFamily) {
    auto c = Cidr::parse("127.1.0.0/16");
    ASSERT_TRUE(c);
    EXPECT_TRUE(c->contains(*IpAddress::parse("127.1.200.3")));
    EXPECT_FALSE(c->contains(*IpAddress::parse("127.2.0.1")));
    EXPECT_FALSE(c->contains(*IpAddress::parse("::ffff:127.1.0.1")));  // different family

    auto odd = Cidr::parse("10.128.0.0/9");
    ASSERT_TRUE(odd);
    EXPECT_TRUE(odd->contains(*IpAddress::parse("10.200.1.1")));
    EXPECT_FALSE(odd->contains(*IpAddress::parse("10.127.1.1")));

    auto v6 = Cidr::parse("2001:db8::/32");
    ASSERT_TRUE(v6);
    EXPECT_TRUE(v6->contains(*IpAddress::parse("2001:db8:ffff::1")));
    EXPECT_EQ(v6->to_string(), "2001:db8::/32");
}

TEST(Cidr, ZeroPrefixMatchesEverythingInFamily) {
    auto all = Cidr::parse("0.0.0.0/0");
    ASSERT_TRUE(all);
    EXPECT_TRUE(all->contains(*IpAddress::parse("203.0.113.9")));
}

TEST(Cidr, RejectsMalformedAndHostBits) {
    for (const auto* text :
         {"10.0.0.0", "10.0.0.0/", "10.0.0.0/33", "10.0.0.1/8", "10.0.0.0/8x", "::/129", "x/8"}) {
        EXPECT_FALSE(Cidr::parse(text)) << text;
    }
}

}  // namespace
}  // namespace hfdns
