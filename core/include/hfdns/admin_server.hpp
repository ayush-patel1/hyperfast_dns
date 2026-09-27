#pragma once

#include <chrono>
#include <cstdint>
#include <memory>
#include <string>

#include "hfdns/error.hpp"
#include "hfdns/net.hpp"

namespace hfdns {

// Management HTTP endpoint on its own thread. It never runs on a data-plane
// worker and never holds data-plane locks (ARCHITECTURE §2).
class AdminServer {
public:
    struct Options {
        IpAddress address;
        std::uint16_t port = 0;  // 0 = pick an ephemeral port (tests)
        std::string version;
    };

    explicit AdminServer(Options options);
    ~AdminServer();
    AdminServer(const AdminServer&) = delete;
    AdminServer& operator=(const AdminServer&) = delete;

    // Binds synchronously (so bind errors are reported to the caller), then
    // serves on a background thread.
    Status start();
    void stop();
    std::uint16_t port() const noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace hfdns
