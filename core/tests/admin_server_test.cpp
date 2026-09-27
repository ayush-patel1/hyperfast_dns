#include "hfdns/admin_server.hpp"

#include <gtest/gtest.h>
#include <httplib.h>
#include <nlohmann/json.hpp>

namespace hfdns {
namespace {

AdminServer::Options loopback_options() {
    return {.address = *IpAddress::parse("127.0.0.1"), .port = 0, .version = "test-1.2.3"};
}

TEST(AdminServer, HealthzReturnsJsonStatus) {
    AdminServer server(loopback_options());
    ASSERT_TRUE(server.start());
    ASSERT_NE(server.port(), 0);

    httplib::Client client("127.0.0.1", server.port());
    auto res = client.Get("/healthz");
    ASSERT_TRUE(res);
    EXPECT_EQ(res->status, 200);
    EXPECT_EQ(res->get_header_value("Content-Type"), "application/json");
    const auto body = nlohmann::json::parse(res->body);
    EXPECT_EQ(body["status"], "ok");
    EXPECT_EQ(body["version"], "test-1.2.3");
    EXPECT_GE(body["uptime_seconds"].get<double>(), 0.0);
    server.stop();
}

TEST(AdminServer, UnknownPathIsJson404) {
    AdminServer server(loopback_options());
    ASSERT_TRUE(server.start());
    httplib::Client client("127.0.0.1", server.port());
    auto res = client.Get("/nope");
    ASSERT_TRUE(res);
    EXPECT_EQ(res->status, 404);
    EXPECT_TRUE(nlohmann::json::accept(res->body)) << res->body;
}

TEST(AdminServer, BindConflictIsReportedNotThrown) {
    AdminServer first(loopback_options());
    ASSERT_TRUE(first.start());
    auto opts = loopback_options();
    opts.port = first.port();
    AdminServer second(opts);
    auto status = second.start();
    ASSERT_FALSE(status);
    EXPECT_EQ(status.error().code, ErrorCode::NetworkError);
}

TEST(AdminServer, StopIsIdempotent) {
    AdminServer server(loopback_options());
    ASSERT_TRUE(server.start());
    server.stop();
    server.stop();
}

}  // namespace
}  // namespace hfdns
